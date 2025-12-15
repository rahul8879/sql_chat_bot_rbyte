import operator
from typing import Annotated

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.utilities import SQLDatabase
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from azure_sql_agent.config import load_database_config, load_openai_config
from azure_sql_agent.connections import build_azure_chat_llm, build_sql_database
from azure_sql_agent.tools import create_sql_tools


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]


def build_sql_agent(db: SQLDatabase, llm: BaseLanguageModel):
    """Construct a LangGraph SQL agent wired with the given DB and LLM."""
    tools = create_sql_tools(db, llm)
    # Use tool_choice if supported; otherwise fallback
    try:
        llm_with_tools = llm.bind_tools(tools, tool_choice="auto")
    except Exception:
        llm_with_tools = llm.bind_tools(tools)

    def _ensure_message(msg):
        if isinstance(msg, str):
            return HumanMessage(content=msg)
        return msg

    def agent_node(state: AgentState):
        system_prompt = (
            "You are an expert Data analyst SQL assistant for Azure SQL Database or Fabric T-SQL endpoints. "
            "You must answer by using the provided tools in this order when needed: "
            "get_database_schema -> generate_sql_query -> validate_sql_query -> execute_sql_query. "
            "Never return raw SQL as the final answer; always execute the query and return results. "
            "Return a concise narrative summary AND, when rows are present, a clear table. "
            "Only use read-only SQL (SELECT/CTE). Always inspect schema before generating SQL."
        )
        user_messages = [_ensure_message(m) for m in state["messages"]]
        return {
            "messages": [
                llm_with_tools.invoke([SystemMessage(content=system_prompt)] + user_messages)
            ]
        }

    def should_continue(state: AgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")

    return builder.compile()


def create_agent_from_env():
    """Build a ready-to-use agent using environment-based configuration."""
    openai_cfg = load_openai_config()
    sql_cfg = load_database_config()

    llm = build_azure_chat_llm(openai_cfg)
    db = build_sql_database(sql_cfg)
    return build_sql_agent(db, llm), db, llm

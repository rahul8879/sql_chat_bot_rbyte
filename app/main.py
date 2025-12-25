import json
import logging
import logging.handlers
import threading
import uuid
from datetime import datetime
from pathlib import Path
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk._logs import LoggingHandler
from azure.data.tables import TableServiceClient
import os

BASE_DIR = Path(__file__).resolve().parent.parent

from azure_sql_agent import create_agent_from_env


app = FastAPI(title="Azure SQL LangGraph Agent")
logger = logging.getLogger("azure_sql_agent_app")
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "12"))

# Logging: console by default; optional file logs for local use.
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
    if os.getenv("LOG_TO_FILE", "0") == "1":
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "agent.log", maxBytes=1_000_000, backupCount=5
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Optional: export logs to Azure Monitor / App Insights if connection string provided
conn_str = os.getenv("AZURE_MONITOR_CONNECTION_STRING")
if conn_str:
    lp = LoggerProvider()
    exporter = AzureMonitorLogExporter(connection_string=conn_str)
    lp.add_log_record_processor(BatchLogRecordProcessor(exporter))
    otel_handler = LoggingHandler(logger_provider=lp, level=logging.INFO)
    logger.addHandler(otel_handler)
    logger.info("Azure Monitor logging enabled")
else:
    logger.info("AZURE_MONITOR_CONNECTION_STRING not set; Azure Monitor logging disabled")

# Lazy-initialized resources to avoid failing the host on startup.
_agent_lock = threading.Lock()
_agent_bundle = None


def _build_table_client():
    storage_conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    table_name = os.getenv("AZURE_TABLE_NAME", "AgentLogs")
    if not storage_conn:
        logger.info("AZURE_STORAGE_CONNECTION_STRING not set; Azure Table logging disabled")
        return None
    try:
        ts = TableServiceClient.from_connection_string(storage_conn)
        ts.create_table_if_not_exists(table_name=table_name)
        logger.info("Azure Table logging enabled (table=%s)", table_name)
        return ts.get_table_client(table_name=table_name)
    except Exception as exc:
        logger.exception("Failed to enable Azure Table logging: %s", exc)
        return None


def _get_agent_bundle():
    global _agent_bundle
    if _agent_bundle is not None:
        return _agent_bundle
    with _agent_lock:
        if _agent_bundle is not None:
            return _agent_bundle
        agent, db, llm = create_agent_from_env()
        table_client = _build_table_client()
        _agent_bundle = (agent, db, llm, table_client)
        return _agent_bundle


class QueryRequest(BaseModel):
    question: str


@app.post("/ask")
def ask(req: QueryRequest):
    session_id = str(uuid.uuid4())
    try:
        agent, _db, _llm, table_client = _get_agent_bundle()
        result = agent.invoke(
            {"messages": [HumanMessage(content=req.question)]},
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )
        messages = result.get("messages", [])

        # Prefer the last AIMessage in the trace (skip tool/human messages)
        ai_msg = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            messages[-1] if messages else None,
        )
        answer = getattr(ai_msg, "content", str(ai_msg))

        # Attempt to pull the executed query if present in tool output
        executed_query = None
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                continue
            if isinstance(getattr(msg, "content", None), dict):
                executed_query = msg.content.get("query") or executed_query
            elif isinstance(getattr(msg, "content", None), list):
                for item in msg.content:
                    if isinstance(item, dict) and "query" in item:
                        executed_query = item["query"]
                        break

        logger.info(
            "session=%s question=%s executed_query=%s answer=%s",
            session_id,
            req.question,
            executed_query,
            answer,
        )

        if table_client:
            try:
                entity = {
                    "PartitionKey": datetime.utcnow().date().isoformat(),
                    "RowKey": session_id,
                    "Question": req.question,
                    "Answer": answer if isinstance(answer, str) else json.dumps(answer),
                    "ExecutedQuery": executed_query or "",
                    "TimestampUtc": datetime.utcnow().isoformat(),
                }
                table_client.upsert_entity(entity)
            except Exception as exc:
                logger.exception("session=%s failed to write to Azure Table: %s", session_id, exc)

        return {"session_id": session_id, "answer": answer, "query": executed_query}
    except Exception as exc:  # pragma: no cover
        logger.exception("session=%s error processing request", session_id)
        raise HTTPException(status_code=500, detail=str(exc))



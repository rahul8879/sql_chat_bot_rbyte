import json
import logging
import logging.handlers
import sys
import uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk._logs import LoggingHandler
from azure.data.tables import TableServiceClient
import os


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

load_dotenv()

from azure_sql_agent import create_agent_from_env


app = FastAPI(title="Azure SQL LangGraph Agent")
agent, db, llm = create_agent_from_env()
logger = logging.getLogger("azure_sql_agent_app")
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "12"))

# File-based logging for session/question/query/answer
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
if not logger.handlers:
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "agent.log", maxBytes=1_000_000, backupCount=5
    )
    fmt = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    # Also keep console output
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

# Optional: log to Azure Table Storage
table_client = None
storage_conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
table_name = os.getenv("AZURE_TABLE_NAME", "AgentLogs")
if storage_conn:
    try:
        ts = TableServiceClient.from_connection_string(storage_conn)
        ts.create_table_if_not_exists(table_name=table_name)
        table_client = ts.get_table_client(table_name=table_name)
        logger.info("Azure Table logging enabled (table=%s)", table_name)
    except Exception as exc:
        logger.exception("Failed to enable Azure Table logging: %s", exc)
else:
    logger.info("AZURE_STORAGE_CONNECTION_STRING not set; Azure Table logging disabled")


class QueryRequest(BaseModel):
    question: str


@app.post("/ask")
def ask(req: QueryRequest):
    session_id = str(uuid.uuid4())
    try:
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


@app.get("/healthz")
def healthz():
    try:
        # Lightweight check; if the engine is unhealthy this will raise
        db.run("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

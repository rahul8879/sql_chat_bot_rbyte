import logging
import os

from fastapi import FastAPI, HTTPException
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from pydantic import BaseModel

from azure_sql_agent.config import load_database_config
from azure_sql_agent.token_connect import connect_with_default_credential

app = FastAPI(title="Dummy Health App")
logger = logging.getLogger("dummy_app")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Optional: Azure Monitor logging (safe init for testing).
conn_str = os.getenv("AZURE_MONITOR_CONNECTION_STRING")
if conn_str:
    try:
        lp = LoggerProvider()
        exporter = AzureMonitorLogExporter(connection_string=conn_str)
        lp.add_log_record_processor(BatchLogRecordProcessor(exporter))
        otel_handler = LoggingHandler(logger_provider=lp, level=logging.INFO)
        logger.addHandler(otel_handler)
        logger.info("Azure Monitor logging enabled (dummy)")
    except Exception as exc:
        logger.exception("Azure Monitor logging failed (dummy): %s", exc)
else:
    logger.info("AZURE_MONITOR_CONNECTION_STRING not set; Azure Monitor logging disabled (dummy)")


class QueryRequest(BaseModel):
    question: str


def _build_llm() -> AzureChatOpenAI:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("OPENAI_API_VERSION")
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

    missing = [name for name, value in {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_DEPLOYMENT_NAME": deployment,
        "AZURE_OPENAI_API_VERSION": api_version,
        "AZURE_OPENAI_API_KEY": api_key,
    }.items() if not value]

    if missing:
        raise ValueError(f"Missing Azure OpenAI environment variables: {', '.join(missing)}")

    return AzureChatOpenAI(
        azure_deployment=deployment,
        azure_endpoint=endpoint,
        api_key=api_key,
        openai_api_version=api_version,
        temperature=0.0,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "dummy"}


@app.get("/ping")
def ping():
    return {"pong": True}


@app.post("/ask")
def ask(req: QueryRequest):
    try:
        llm = _build_llm()
        msg = llm.invoke([HumanMessage(content=req.question)])
        return {"answer": getattr(msg, "content", str(msg))}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/dbcheck")
def dbcheck():
    try:
        cfg = load_database_config()
        db, _engine = connect_with_default_credential(
            server=cfg.server,
            database=cfg.database,
            driver=cfg.driver,
            include_tables=cfg.allowed_tables,
            sample_rows_in_table_info=cfg.schema_sample_rows,
        )
        db.run("SELECT 1")
        return {"status": "ok", "db": cfg.database}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

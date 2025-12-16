# Azure SQL  Agent

Agent that converts natural language to SQL for Azure SQL Database (or Fabric SQL endpoints) using LangGraph/LangChain/MAF and Azure OpenAI. Includes a FastAPI wrapper, notebook for experimentation, and Azure Monitor logging.

## Project layout
- `azure_sql_agent/`
  - `config.py` – loads env vars (OpenAI + SQL).
  - `connections.py` – builds LLM and SQL connections (token-based DefaultAzureCredential flow).
  - `token_connect.py` – DefaultAzureCredential + pyodbc token helper.
  - `tools.py` – schema/query generation/validation/execution tools.
  - `agent.py` – LangGraph wiring and agent factory.
- `app/main.py` – FastAPI server exposing `/ask` and `/healthz`, logging to file/console and Azure Monitor (if configured).
- `notebook/azure_sql_agent.ipynb` – notebook to test the agent directly.
- `logs/agent.log` – local rotating log file (session/question/query/answer).
- `.env` / `.env_example` – environment variables.
- `requirements.txt` – Python dependencies.

## Prerequisites
- Python 3.10+ (virtualenv recommended).
- ODBC Driver 18 for SQL Server + unixODBC installed on the host.
- `az login` (or run in Azure with Managed Identity) so DefaultAzureCredential can get a token.
- Network access to your SQL server (public IP allowlisted or private endpoint/VNet).

## Environment variables (`.env`)
Required:
- `AZURE_OPENAI_API_KEY` – your Azure OpenAI key.
- `AZURE_OPENAI_ENDPOINT` – e.g. `https://<resource>.openai.azure.com/`.
- `AZURE_OPENAI_DEPLOYMENT_NAME` – deployment name for chat model.
- `OPENAI_API_VERSION` – e.g. `2024-02-15-preview`.
- `AZURE_SQL_SERVER` – e.g. `rbyte-sql-server.database.windows.net`.
- `AZURE_SQL_DATABASE` – target DB name.
- `AZURE_SQL_DRIVER` – `ODBC Driver 18 for SQL Server` (default).

Optional:
- `AZURE_MONITOR_CONNECTION_STRING` – Application Insights connection string to export logs.
- `SQL_ALLOWED_TABLES` – comma-separated table names to expose to the agent (useful to limit to 1-2 tables).
- `SQL_SCHEMA_SAMPLE_ROWS` – rows to include per table when building schema prompts (default 3).
- `AGENT_RECURSION_LIMIT` – LangGraph recursion limit for a single request (default 12) to avoid tool loops.

Copy `.env_example` to `.env` and fill in your values (do not commit secrets).

## Setup
```bash
python -m venv da-env
source da-env/bin/activate
pip install -r requirements.txt
```

## Run the FastAPI service
```bash
source da-env/bin/activate
uvicorn app.main:app --reload
```
- Endpoint: `POST /ask` with JSON `{"question": "…"}` → returns answer + executed query.
- Health: `GET /healthz`.
- Logs: `logs/agent.log` and stdout; if `AZURE_MONITOR_CONNECTION_STRING` is set, logs also go to Application Insights (`traces` table).

## Test in the notebook
Open `notebook/azure_sql_agent.ipynb` and run the cells. It uses the same env and token-based connection via DefaultAzureCredential.

## Notes
- The agent enforces read-only queries (SELECT/CTE).
- It fetches schema via LangChain `SQLDatabase` and executes queries against your Azure SQL DB.
- Logging includes session ID, question, executed query, and answer. Configure Azure Monitor to centralize logs.***

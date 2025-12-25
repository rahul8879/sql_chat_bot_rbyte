# Azure Function App Deployment Checklist

## Deploy
- `func azure functionapp publish rbyte-fatima`

## App settings (Azure)
- `FUNCTIONS_WORKER_RUNTIME=python`
- `FUNCTIONS_EXTENSION_VERSION=~4`
- `AzureWebJobsFeatureFlags=EnableWorkerIndexing`
- `AzureWebJobsStorage=<storage-connection-string>`
- `AZURE_OPENAI_API_KEY=<key>`
- `AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/`
- `AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-chat`
- `AZURE_OPENAI_API_VERSION=2024-02-15-preview`
- `AZURE_SQL_SERVER=rbyte-sql-server.database.windows.net`
- `AZURE_SQL_DATABASE=rbyte-ai-db`
- `AZURE_SQL_DRIVER=ODBC Driver 18 for SQL Server`

## Managed Identity
- Enable system-assigned identity on the Function App.

## SQL Server networking
- Allow Azure services **or** add Function App outbound IPs to firewall rules.

## SQL DB permissions (run in rbyte-ai-db)
```sql
CREATE USER [rbyte-fatima] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [rbyte-fatima];
```

## Restart
- `az functionapp restart --name rbyte-fatima --resource-group rbyte-fatima_group`

## Test
- `https://<app>.azurewebsites.net/docs`
- `POST https://<app>.azurewebsites.net/ask`

## app/main.py changes
- `.env` loading removed.
- Agent/DB/table client init is lazy to avoid host startup crashes.
- Console logging by default; file logging only if `LOG_TO_FILE=1`.

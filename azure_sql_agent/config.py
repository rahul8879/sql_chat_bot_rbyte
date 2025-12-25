import os
from dataclasses import dataclass



@dataclass
class OpenAIConfig:
    azure_endpoint: str
    azure_deployment: str
    api_version: str
    api_key: str
    temperature: float = 0.0


@dataclass
class DatabaseConfig:
    server: str
    database: str
    driver: str = "ODBC Driver 18 for SQL Server"
    schema_sample_rows: int = 3
    allowed_tables: list[str] | None = None


def load_openai_config() -> OpenAIConfig:
    """Read Azure OpenAI settings from environment variables."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("OPENAI_API_VERSION")
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    temperature = float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.0"))

    missing = [name for name, value in {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_DEPLOYMENT_NAME": deployment,
        "AZURE_OPENAI_API_VERSION": api_version,
        "AZURE_OPENAI_API_KEY": api_key,
    }.items() if not value]

    if missing:
        raise ValueError(f"Missing Azure OpenAI environment variables: {', '.join(missing)}")

    return OpenAIConfig(
        azure_endpoint=endpoint,
        azure_deployment=deployment,
        api_version=api_version,
        api_key=api_key,
        temperature=temperature,
    )


def load_database_config() -> DatabaseConfig:
    """Read SQL connection info for token-based Azure SQL auth."""
    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    driver = os.getenv("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    schema_sample_rows = int(os.getenv("SQL_SCHEMA_SAMPLE_ROWS", "3"))
    allowed_tables_env = os.getenv("SQL_ALLOWED_TABLES")
    allowed_tables = ['Customers']  # Default tables
    if allowed_tables_env:
        allowed_tables = [tbl.strip() for tbl in allowed_tables_env.split(",") if tbl.strip()]

    if not (server and database):
        raise ValueError(
            "Set AZURE_SQL_SERVER and AZURE_SQL_DATABASE for token-based Azure SQL connection."
        )

    return DatabaseConfig(
        server=server,
        database=database,
        driver=driver,
        schema_sample_rows=schema_sample_rows,
        allowed_tables=allowed_tables,
    )

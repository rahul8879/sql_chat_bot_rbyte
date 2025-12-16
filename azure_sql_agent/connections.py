from langchain_community.utilities import SQLDatabase
from langchain_openai import AzureChatOpenAI

from azure_sql_agent.config import DatabaseConfig, OpenAIConfig
from azure_sql_agent.token_connect import connect_with_default_credential


def build_azure_chat_llm(config: OpenAIConfig) -> AzureChatOpenAI:
    """Return an Azure Chat LLM configured for tool use."""
    return AzureChatOpenAI(
        azure_deployment=config.azure_deployment,
        azure_endpoint=config.azure_endpoint,
        api_key=config.api_key,
        openai_api_version=config.api_version,
        temperature=config.temperature,
    )


def build_sql_database(config: DatabaseConfig) -> SQLDatabase:
    """Create a SQLDatabase wrapper using DefaultAzureCredential token injection."""
    db, _engine = connect_with_default_credential(
        server=config.server,
        database=config.database,
        driver=config.driver,
        include_tables=config.allowed_tables,
        sample_rows_in_table_info=config.schema_sample_rows,
    )
    return db

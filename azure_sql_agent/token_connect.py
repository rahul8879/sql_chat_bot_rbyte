import struct
import urllib.parse
from typing import Tuple

from azure.identity import DefaultAzureCredential
from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine

# pyodbc access token connection attribute
SQL_COPT_SS_ACCESS_TOKEN = 1256


def connect_with_default_credential(
    server: str,
    database: str,
    driver: str = "ODBC Driver 18 for SQL Server",
    include_tables: list[str] | None = None,
    sample_rows_in_table_info: int = 3,
) -> Tuple[SQLDatabase, object]:
    """
    Connect to Azure SQL using DefaultAzureCredential and return (SQLDatabase, engine).
    This uses Active Directory access tokens (MFA-friendly) without embedding credentials in the URI.
    include_tables: optional whitelist of tables to expose to the agent.
    sample_rows_in_table_info: number of sample rows per table when introspecting schema.
    """
    print(f"[connect_with_default_credential] server={server}, database={database}, driver={driver}")
    print("[connect_with_default_credential] acquiring token via DefaultAzureCredential...")
    credential = DefaultAzureCredential()
    token = credential.get_token("https://database.windows.net/.default")
    print("[connect_with_default_credential] token acquired.")

    token_bytes = token.token.encode("UTF-16-LE")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    params = urllib.parse.quote_plus(
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    conn_str = f"mssql+pyodbc:///?odbc_connect={params}"
    print(f"[connect_with_default_credential] connection string (pyodbc-encoded) ready.")

    engine = create_engine(
        conn_str,
        connect_args={"attrs_before": {SQL_COPT_SS_ACCESS_TOKEN: token_struct}},
    )
    print("[connect_with_default_credential] engine created, wrapping with SQLDatabase...")
    db = SQLDatabase(
        engine,
        include_tables=include_tables,
        sample_rows_in_table_info=sample_rows_in_table_info,
    )
    print("[connect_with_default_credential] SQLDatabase ready.")
    return db, engine

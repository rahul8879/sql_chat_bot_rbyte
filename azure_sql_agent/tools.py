import logging
import re
from typing import List

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_community.utilities import SQLDatabase

logger = logging.getLogger("azure_sql_agent_app")


def _strip_sql_fences(query: str) -> str:
    clean = query.strip()
    clean = re.sub(r"```sql\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"```\s*", "", clean, flags=re.IGNORECASE)
    return clean.strip()


def _validate_select_only(query: str) -> str:
    clean_query = _strip_sql_fences(query)
    lowered = clean_query.lower()

    if not lowered.startswith(("select", "with")):
        return "Error: Only SELECT or CTE queries are allowed."

    forbidden = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "truncate ",
        "create ",
        "grant ",
        "revoke ",
        "exec ",
        "execute ",
        "merge ",
    ]

    if any(term in lowered for term in forbidden):
        return "Error: Query contained a non-read keyword."

    return clean_query


def create_sql_tools(db: SQLDatabase, llm: BaseLanguageModel) -> List:
    """Create tool functions bound to the provided database and model."""
    schema_snapshot = db.get_table_info()
    table_names = {t.lower(): t for t in db.get_usable_table_names()}

    def _closest_table(name: str) -> str | None:
        lowered = name.lower()
        if lowered in table_names:
            return table_names[lowered]
        # simple fuzzy match on prefix/substring
        candidates = list(table_names.values())
        for candidate in candidates:
            if lowered in candidate.lower() or candidate.lower() in lowered:
                return candidate
        return None

    @tool
    def get_database_schema(table_name: str | None = None) -> str:
        """Get schema details for the database. Use before generating SQL."""
        if table_name:
            try:
                if table_name.lower() in table_names:
                    return db.get_table_info([table_names[table_name.lower()]])
                close = _closest_table(table_name)
                if close:
                    return (
                        f"Requested table '{table_name}' not found; using closest match '{close}'.\n"
                        f"{db.get_table_info([close])}"
                    )
                return (
                    f"Requested table '{table_name}' not found. "
                    f"Available tables: {list(table_names.values())}.\nFull schema:\n{schema_snapshot}"
                )
            except Exception:
                return (
                    f"Error getting table '{table_name}'. "
                    f"Available tables: {list(table_names.values())}.\nFull schema:\n{schema_snapshot}"
                )
        return schema_snapshot

    @tool
    def generate_sql_query(question: str, schema_info: str | None = None) -> str:
        """Generate a SELECT query for the given natural language question."""
        schema_text = schema_info if schema_info else schema_snapshot
        prompt = f"""You translate natural language into safe T-SQL.
Use only the provided schema. Do not invent tables or columns.
Only produce a single SQL query wrapped in ```sql``` fences.

Schema:
{schema_text}

Question: {question}
SQL:"""
        response = llm.invoke(
            [
                SystemMessage(
                    content="You are a senior data analyst targeting Azure SQL DB or Fabric lakehouse SQL endpoints."
                ),
                HumanMessage(content=prompt),
            ]
        )
        return response.content.strip()

    @tool
    def validate_sql_query(query: str) -> str:
        """Validate that the SQL query is read-only and safe."""
        return _validate_select_only(query)

    @tool
    def execute_sql_query(sql_query: str):
        """Validate and run the SQL query against the configured database."""
        validation = _validate_select_only(sql_query)
        if validation.startswith("Error:"):
            return validation

        try:
            logger.info("executing_query=%s", validation)
            result = db.run(validation)
            # Normalize result for better downstream formatting
            if isinstance(result, list):
                return {
                    "rows": result,
                    "row_count": len(result),
                    "query": validation,
                }
            return result
        except Exception as exc:  # pragma: no cover - execution errors surfaced to fixer
            return f"Execution error: {exc}"

    @tool
    def fix_sql_error(original_query: str, error_message: str, question: str) -> str:
        """Fix a failed SQL query by analyzing the error and regenerating it."""
        prompt = f"""The SQL query below failed. Re-write a corrected query.
Rules:
- Keep it read-only (SELECT/CTE only).
- Use existing tables/columns only.
- Prefer explicit column names over SELECT *.
- Return only SQL, wrapped in ```sql``` fences.

Question: {question}
Original query:
{original_query}

Error message: {error_message}

Corrected SQL:"""
        response = llm.invoke(
            [
                SystemMessage(content="You repair T-SQL queries for Azure SQL or Fabric SQL endpoints."),
                HumanMessage(content=prompt),
            ]
        )
        return response.content.strip()

    return [
        get_database_schema,
        generate_sql_query,
        validate_sql_query,
        execute_sql_query,
        fix_sql_error,
    ]

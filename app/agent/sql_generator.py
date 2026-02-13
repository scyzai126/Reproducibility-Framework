import re

from openai import AsyncOpenAI

from app.config import settings

DANGEROUS_PATTERNS = re.compile(
    r"\b(DROP|TRUNCATE|ALTER|DELETE\s+FROM|UPDATE\s+.*SET)\b", re.IGNORECASE
)

SYSTEM_PROMPT = (
    "You are a SQL expert. Given the user-provided data, generate a single valid "
    "MySQL SELECT query that would answer a reasonable analytical question about the "
    "data. Return ONLY the raw SQL query — no markdown, no explanation."
)


async def generate_sql(file_content: str, schema_hint: str = "") -> str:
    """Send file content to OpenAI and return a generated SQL query string."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    user_message = f"Data:\n{file_content}"
    if schema_hint:
        user_message = f"Database schema:\n{schema_hint}\n\n{user_message}"

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
    )

    sql = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    sql = re.sub(r"^```(?:sql)?\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql)

    _validate_sql(sql)
    return sql


def _validate_sql(sql: str) -> None:
    """Reject queries containing dangerous DDL/DML statements."""
    if DANGEROUS_PATTERNS.search(sql):
        raise ValueError(
            f"Generated SQL contains a forbidden statement: {sql[:120]}..."
        )

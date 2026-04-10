from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def execute_query(session: AsyncSession, sql: str) -> list[dict]:
    """Execute a raw SQL string and return results as a list of dicts."""
    try:
        result = await session.execute(text(sql))
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as exc:
        raise RuntimeError(f"Query execution failed: {exc}") from exc

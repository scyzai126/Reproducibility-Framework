from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.file_reader import read_file
from app.agent.sql_generator import generate_sql
from app.agent.query_executor import execute_query
from app.config import settings
from app.plugins import plugin_registry


async def run_agent(file_path: str, session: AsyncSession) -> dict:
    """Main agent loop: read -> generate SQL -> execute -> enrich -> summarize."""

    # 1. Read file content
    file_content = read_file(file_path)

    # 2. Generate SQL from content
    sql = await generate_sql(file_content)

    # 3. Execute SQL against MySQL
    query_results = await execute_query(session, sql)

    # 4. Enrich with plugins
    enrichments: dict[str, dict] = {}
    for plugin in plugin_registry.get_all():
        try:
            enrichment = await plugin.fetch(
                {"query_results": query_results, "file_content": file_content}
            )
            enrichments[plugin.name] = enrichment
        except Exception as exc:
            enrichments[plugin.name] = {"error": str(exc)}

    # 5. Summarize with a second LLM call
    summary = await _summarize(file_content, sql, query_results, enrichments)

    return {
        "sql": sql,
        "query_results": query_results,
        "enrichments": enrichments,
        "summary": summary,
    }


async def _summarize(
    file_content: str,
    sql: str,
    query_results: list[dict],
    enrichments: dict,
) -> str:
    """Use OpenAI to produce a human-friendly summary of all results."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = (
        f"Original data (truncated):\n{file_content[:500]}\n\n"
        f"Generated SQL:\n{sql}\n\n"
        f"Query results:\n{query_results}\n\n"
        f"Enrichments:\n{enrichments}\n\n"
        "Please provide a concise summary of the findings."
    )

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful data analyst. Summarize the results clearly.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    return response.choices[0].message.content.strip()

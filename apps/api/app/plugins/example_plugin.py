import httpx

from app.plugins.base import BasePlugin
from app.plugins import plugin_registry


class ExamplePlugin(BasePlugin):
    """Sample plugin that calls a placeholder REST API."""

    @property
    def name(self) -> str:
        return "example"

    @property
    def description(self) -> str:
        return "Calls httpbin.org as a demo external API enrichment."

    async def fetch(self, params: dict) -> dict:
        row_count = len(params.get("query_results", []))
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://httpbin.org/post",
                json={"row_count": row_count, "source": "ai-agent"},
            )
            response.raise_for_status()
            return {"status": response.status_code, "echo": response.json().get("json")}


# Self-register on import
plugin_registry.register(ExamplePlugin())

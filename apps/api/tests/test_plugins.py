import pytest
from app.plugins import PluginRegistry
from app.plugins.base import BasePlugin


class DummyPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy plugin for testing."

    async def fetch(self, params: dict) -> dict:
        return {"result": "ok", "rows": len(params.get("query_results", []))}


def test_registry_register_and_get():
    registry = PluginRegistry()
    plugin = DummyPlugin()
    registry.register(plugin)
    assert registry.get("dummy") is plugin


def test_registry_get_all():
    registry = PluginRegistry()
    registry.register(DummyPlugin())
    assert len(registry.get_all()) == 1


def test_registry_get_missing():
    registry = PluginRegistry()
    assert registry.get("nonexistent") is None


@pytest.mark.asyncio
async def test_dummy_plugin_fetch():
    plugin = DummyPlugin()
    result = await plugin.fetch({"query_results": [{"id": 1}, {"id": 2}]})
    assert result == {"result": "ok", "rows": 2}

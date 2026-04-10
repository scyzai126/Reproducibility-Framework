from app.plugins.base import BasePlugin


class PluginRegistry:
    """Registry that holds all available plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> BasePlugin | None:
        return self._plugins.get(name)

    def get_all(self) -> list[BasePlugin]:
        return list(self._plugins.values())


plugin_registry = PluginRegistry()


def auto_discover() -> None:
    """Import built-in plugins so they self-register."""
    from app.plugins import example_plugin  # noqa: F401

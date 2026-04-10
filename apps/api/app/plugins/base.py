from abc import ABC, abstractmethod


class BasePlugin(ABC):
    """Abstract base class for all enrichment plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what this plugin does."""

    @abstractmethod
    async def fetch(self, params: dict) -> dict:
        """Fetch enrichment data. Receives query results and file content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.settings import TitleMCPSettings


@dataclass(slots=True)
class PluginContext:
    settings: TitleMCPSettings
    adapters: AdapterRegistry


class TitleMCPPlugin(Protocol):
    name: str

    def register(self, context: PluginContext) -> None:
        """Register adapters or other platform extensions."""

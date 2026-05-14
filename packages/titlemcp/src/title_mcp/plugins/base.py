from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.capabilities.registry import CapabilityRegistry
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources.registry import SourceConnectorRegistry
from title_mcp.vendors.registry import VendorConnectorRegistry


@dataclass(slots=True)
class PluginContext:
    settings: TitleMCPSettings
    adapters: AdapterRegistry
    capabilities: CapabilityRegistry
    sources: SourceConnectorRegistry
    vendors: VendorConnectorRegistry


class TitleMCPPlugin(Protocol):
    name: str

    def register(self, context: PluginContext) -> None:
        """Register adapters, source connectors, vendor connectors, or manifests."""

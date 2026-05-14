from __future__ import annotations

import asyncio

from title_mcp.adapters.registry import AdapterRegistry, create_default_adapter_registry
from title_mcp.capabilities.registry import (
    CapabilityRegistry,
    create_default_capability_registry,
)
from title_mcp.observability import configure_logging
from title_mcp.plugins import PluginContext, load_plugins
from title_mcp.services import DocumentAnalysisService, WorkflowService
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources.registry import SourceConnectorRegistry, create_default_source_registry
from title_mcp.state import WorkflowRepository, create_repository
from title_mcp.vendors.registry import VendorConnectorRegistry, create_default_vendor_registry
from title_mcp.workflows import WorkflowEngine


class TitleMCPPlatform:
    def __init__(
        self,
        *,
        settings: TitleMCPSettings,
        repository: WorkflowRepository | None = None,
        adapters: AdapterRegistry | None = None,
        capabilities: CapabilityRegistry | None = None,
        sources: SourceConnectorRegistry | None = None,
        vendors: VendorConnectorRegistry | None = None,
        load_entry_point_adapters: bool | None = None,
        load_entry_point_capabilities: bool | None = None,
        load_entry_point_sources: bool | None = None,
        load_entry_point_vendors: bool | None = None,
        load_entry_point_plugins: bool | None = None,
    ) -> None:
        self.settings = settings
        load_capabilities = (
            settings.load_entry_point_capabilities
            if load_entry_point_capabilities is None
            else load_entry_point_capabilities
        )
        load_adapters = (
            settings.load_entry_point_adapters
            if load_entry_point_adapters is None
            else load_entry_point_adapters
        )
        load_sources = (
            settings.load_entry_point_sources
            if load_entry_point_sources is None
            else load_entry_point_sources
        )
        load_vendors = (
            settings.load_entry_point_vendors
            if load_entry_point_vendors is None
            else load_entry_point_vendors
        )
        load_plugins_flag = (
            settings.load_entry_point_plugins
            if load_entry_point_plugins is None
            else load_entry_point_plugins
        )
        self.repository = repository or create_repository(settings)
        self.capabilities = capabilities or create_default_capability_registry(
            include_entry_points=load_capabilities
        )
        self.adapters = adapters or create_default_adapter_registry(
            include_entry_points=load_adapters,
            config_path=settings.jurisdiction_config_path,
        )
        self.sources = sources or create_default_source_registry(include_entry_points=load_sources)
        self.vendors = vendors or create_default_vendor_registry(include_entry_points=load_vendors)
        self.document_analysis = DocumentAnalysisService()
        self.engine = WorkflowEngine(
            repository=self.repository,
            adapters=self.adapters,
            concurrency=settings.background_worker_concurrency,
        )
        self.workflows = WorkflowService(repository=self.repository, engine=self.engine)
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._load_plugins = load_plugins_flag

    async def initialize(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            configure_logging(self.settings.log_level, json_logs=self.settings.log_json)
            if self._load_plugins:
                load_plugins(
                    PluginContext(
                        settings=self.settings,
                        adapters=self.adapters,
                        capabilities=self.capabilities,
                        sources=self.sources,
                        vendors=self.vendors,
                    )
                )
            await self.repository.initialize()
            self._initialized = True

    async def shutdown(self) -> None:
        await self.engine.shutdown()
        close = getattr(self.repository, "close", None)
        if close:
            await close()

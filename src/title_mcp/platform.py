from __future__ import annotations

import asyncio

from title_mcp.adapters.registry import AdapterRegistry, create_default_adapter_registry
from title_mcp.observability import configure_logging
from title_mcp.plugins import PluginContext, load_plugins
from title_mcp.services import DocumentAnalysisService, WorkflowService
from title_mcp.settings import TitleMCPSettings
from title_mcp.state import WorkflowRepository, create_repository
from title_mcp.workflows import WorkflowEngine


class TitleMCPPlatform:
    def __init__(
        self,
        *,
        settings: TitleMCPSettings,
        repository: WorkflowRepository | None = None,
        adapters: AdapterRegistry | None = None,
        load_entry_point_plugins: bool = False,
    ) -> None:
        self.settings = settings
        self.repository = repository or create_repository(settings)
        self.adapters = adapters or create_default_adapter_registry(
            include_entry_points=load_entry_point_plugins,
            config_path=settings.jurisdiction_config_path,
        )
        self.document_analysis = DocumentAnalysisService()
        self.engine = WorkflowEngine(
            repository=self.repository,
            adapters=self.adapters,
            concurrency=settings.background_worker_concurrency,
        )
        self.workflows = WorkflowService(repository=self.repository, engine=self.engine)
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._load_plugins = load_entry_point_plugins

    async def initialize(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            configure_logging(self.settings.log_level, json_logs=self.settings.log_json)
            if self._load_plugins:
                load_plugins(PluginContext(settings=self.settings, adapters=self.adapters))
            await self.repository.initialize()
            self._initialized = True

    async def shutdown(self) -> None:
        await self.engine.shutdown()
        close = getattr(self.repository, "close", None)
        if close:
            await close()

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

from title_mcp.adapters.base import JurisdictionAdapter
from title_mcp.adapters.configurable import load_configured_adapters
from title_mcp.adapters.default import (
    BaltimoreCityPublicRecordsAdapter,
    FloridaTitleAdapter,
    GenericTitleAdapter,
    MiamiDadePublicRecordsAdapter,
)
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[JurisdictionAdapter] = []

    def register(self, adapter: JurisdictionAdapter) -> None:
        adapter_id = getattr(adapter, "adapter_id", adapter.__class__.__qualname__)
        self._adapters = [
            existing
            for existing in self._adapters
            if getattr(existing, "adapter_id", existing.__class__.__qualname__) != adapter_id
        ]
        self._adapters.append(adapter)
        self._adapters.sort(key=lambda item: item.priority, reverse=True)

    def resolve(
        self,
        jurisdiction: Jurisdiction,
        kind: WorkflowKind | None = None,
    ) -> JurisdictionAdapter:
        for adapter in self._adapters:
            if _supports_kind(adapter, kind) and adapter.supports(jurisdiction):
                return adapter
        suffix = f" and workflow {kind.value}" if kind else ""
        raise LookupError(f"No adapter registered for jurisdiction {jurisdiction.key}{suffix}")

    def all(self) -> list[JurisdictionAdapter]:
        return list(self._adapters)

    def load_entry_points(self, group: str = "title_mcp.adapters") -> None:
        for entry_point in entry_points(group=group):
            adapter_cls = entry_point.load()
            self.register(adapter_cls())

    def load_config_file(self, path: str | Path) -> None:
        for adapter in load_configured_adapters(path):
            self.register(adapter)


def create_default_adapter_registry(
    *,
    include_entry_points: bool = False,
    config_path: str | Path | None = None,
) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(BaltimoreCityPublicRecordsAdapter())
    registry.register(MiamiDadePublicRecordsAdapter())
    registry.register(FloridaTitleAdapter())
    registry.register(GenericTitleAdapter())
    if config_path:
        registry.load_config_file(config_path)
    if include_entry_points:
        registry.load_entry_points()
    return registry


def _supports_kind(adapter: JurisdictionAdapter, kind: WorkflowKind | None) -> bool:
    if kind is None:
        return True
    workflow_kinds = getattr(adapter, "workflow_kinds", None)
    return workflow_kinds is None or kind in workflow_kinds

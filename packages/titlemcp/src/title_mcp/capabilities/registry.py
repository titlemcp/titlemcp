from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from title_mcp.capabilities.base import CapabilityManifest, CapabilityType
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityManifest] = {}

    def register(self, manifest: CapabilityManifest | dict[str, Any]) -> None:
        parsed = CapabilityManifest.model_validate(manifest)
        self._capabilities[parsed.capability_id] = parsed

    def get(self, capability_id: str) -> CapabilityManifest | None:
        return self._capabilities.get(capability_id)

    def all(self) -> list[CapabilityManifest]:
        return sorted(self._capabilities.values(), key=lambda manifest: manifest.capability_id)

    def resolve(
        self,
        jurisdiction: Jurisdiction,
        *,
        kind: WorkflowKind | None = None,
        capability_type: CapabilityType | None = None,
    ) -> list[CapabilityManifest]:
        return [
            manifest
            for manifest in self.all()
            if manifest.supports(jurisdiction, kind, capability_type)
        ]

    def load_entry_points(self, group: str = "title_mcp.capabilities") -> None:
        for entry_point in entry_points(group=group):
            loaded = entry_point.load()
            manifest = loaded() if callable(loaded) else loaded
            self.register(manifest)


def create_default_capability_registry(
    *, include_entry_points: bool = False
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    if include_entry_points:
        registry.load_entry_points()
    return registry

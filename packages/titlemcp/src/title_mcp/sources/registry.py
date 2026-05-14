from __future__ import annotations

from importlib.metadata import entry_points

from title_mcp.domain.models import Jurisdiction
from title_mcp.sources.base import SourceConnector, SourceKind


class SourceConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, SourceConnector] = {}

    def register(self, connector: SourceConnector) -> None:
        self._connectors[connector.source_id] = connector

    def get(self, source_id: str) -> SourceConnector | None:
        return self._connectors.get(source_id)

    def all(self) -> list[SourceConnector]:
        return sorted(
            self._connectors.values(),
            key=lambda connector: (
                connector.descriptor.priority,
                connector.descriptor.jurisdiction_scope.specificity,
            ),
            reverse=True,
        )

    def resolve(
        self,
        jurisdiction: Jurisdiction,
        kind: SourceKind | None = None,
    ) -> SourceConnector:
        for connector in self.all():
            if connector.supports(jurisdiction, kind):
                return connector
        suffix = f" and source kind {kind.value}" if kind else ""
        raise LookupError(
            f"No source connector registered for jurisdiction {jurisdiction.key}{suffix}"
        )

    def load_entry_points(self, group: str = "title_mcp.sources") -> None:
        for entry_point in entry_points(group=group):
            connector_cls = entry_point.load()
            self.register(connector_cls())


def create_default_source_registry(
    *, include_entry_points: bool = False
) -> SourceConnectorRegistry:
    registry = SourceConnectorRegistry()
    if include_entry_points:
        registry.load_entry_points()
    return registry

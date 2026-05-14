from __future__ import annotations

from importlib.metadata import entry_points

from title_mcp.domain.models import Jurisdiction
from title_mcp.vendors.base import VendorConnector, VendorKind


class VendorConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, VendorConnector] = {}

    def register(self, connector: VendorConnector) -> None:
        self._connectors[connector.vendor_id] = connector

    def get(self, vendor_id: str) -> VendorConnector | None:
        return self._connectors.get(vendor_id)

    def all(self) -> list[VendorConnector]:
        return sorted(
            self._connectors.values(),
            key=lambda connector: (
                connector.descriptor.priority,
                max(
                    (scope.specificity for scope in connector.descriptor.jurisdiction_scopes),
                    default=0,
                ),
            ),
            reverse=True,
        )

    def resolve(
        self,
        jurisdiction: Jurisdiction,
        kind: VendorKind | None = None,
    ) -> VendorConnector:
        for connector in self.all():
            if connector.supports(jurisdiction, kind):
                return connector
        suffix = f" and vendor kind {kind.value}" if kind else ""
        raise LookupError(
            f"No vendor connector registered for jurisdiction {jurisdiction.key}{suffix}"
        )

    def load_entry_points(self, group: str = "title_mcp.vendors") -> None:
        for entry_point in entry_points(group=group):
            connector_cls = entry_point.load()
            self.register(connector_cls())


def create_default_vendor_registry(
    *, include_entry_points: bool = False
) -> VendorConnectorRegistry:
    registry = VendorConnectorRegistry()
    if include_entry_points:
        registry.load_entry_points()
    return registry

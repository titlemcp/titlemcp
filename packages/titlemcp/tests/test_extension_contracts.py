from __future__ import annotations

import unittest

from title_mcp.adapters import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityRegistry, CapabilityType
from title_mcp.domain import ParcelIdentifier, TitleMatterSnapshot
from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import (
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)
from title_mcp.sources.registry import SourceConnectorRegistry
from title_mcp.state.memory import InMemoryWorkflowRepository
from title_mcp.vendors import (
    VendorDescriptor,
    VendorKind,
    VendorOrderRequest,
    VendorOrderResult,
    VendorOrderStatus,
)
from title_mcp.vendors.registry import VendorConnectorRegistry


class ExtensionContractTests(unittest.IsolatedAsyncioTestCase):
    def test_capability_manifest_resolves_by_jurisdiction_and_workflow(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            CapabilityManifest(
                capability_id="us-oh-franklin-recorder",
                name="Franklin County Recorder",
                capability_types=[CapabilityType.GOVERNMENT_SOURCE],
                jurisdiction_scopes=[
                    JurisdictionScope(country="US", state="OH", county="Franklin County")
                ],
                workflow_kinds=[WorkflowKind.PUBLIC_RECORDS_SEARCH],
            )
        )

        matches = registry.resolve(
            Jurisdiction(country="US", state="OH", county="Franklin County"),
            kind=WorkflowKind.PUBLIC_RECORDS_SEARCH,
            capability_type=CapabilityType.GOVERNMENT_SOURCE,
        )

        self.assertEqual(
            [manifest.capability_id for manifest in matches],
            ["us-oh-franklin-recorder"],
        )

    async def test_source_registry_routes_government_source_connector(self) -> None:
        registry = SourceConnectorRegistry()
        connector = _FakeRecorderSource()
        registry.register(connector)

        resolved = registry.resolve(
            Jurisdiction(country="US", state="OH", county="Franklin County"),
            SourceKind.COUNTY_RECORDER,
        )
        result = await resolved.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US", state="OH", county="Franklin County"),
                kind=SourceKind.COUNTY_RECORDER,
                criteria={"party_name": "Example Seller"},
            )
        )

        self.assertIs(resolved, connector)
        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(result.records[0]["instrument_number"], "2025-0001")

    async def test_vendor_registry_routes_service_provider_connector(self) -> None:
        registry = VendorConnectorRegistry()
        connector = _FakeHoaVendor()
        registry.register(connector)

        resolved = registry.resolve(
            Jurisdiction(country="US", state="FL", county="Orange"),
            VendorKind.HOA_ESTOPPEL,
        )
        result = await resolved.submit_order(
            VendorOrderRequest(
                kind=VendorKind.HOA_ESTOPPEL,
                jurisdiction=Jurisdiction(country="US", state="FL", county="Orange"),
                title_matter=TitleMatterSnapshot(file_number="2026-001"),
            )
        )

        self.assertIs(resolved, connector)
        self.assertEqual(result.status, VendorOrderStatus.SUBMITTED)
        self.assertEqual(result.external_order_id, "vendor-123")

    def test_title_matter_primitives_are_normalized(self) -> None:
        snapshot = TitleMatterSnapshot(
            file_number="2026-002",
            parcels=[ParcelIdentifier(parcel_id="A-100", state="fl")],
        )

        self.assertEqual(snapshot.parcels[0].state, "FL")

    def test_platform_owns_all_extension_registries(self) -> None:
        platform = TitleMCPPlatform(
            settings=TitleMCPSettings(
                load_entry_point_adapters=False,
                load_entry_point_capabilities=False,
                load_entry_point_sources=False,
                load_entry_point_vendors=False,
                load_entry_point_toolsets=False,
            ),
            repository=InMemoryWorkflowRepository(),
        )

        self.assertIsInstance(platform.capabilities, CapabilityRegistry)
        self.assertIsInstance(platform.sources, SourceConnectorRegistry)
        self.assertIsInstance(platform.vendors, VendorConnectorRegistry)


class _FakeRecorderSource:
    source_id = "fake-recorder"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Fake Recorder",
        kind=SourceKind.COUNTY_RECORDER,
        jurisdiction_scope=JurisdictionScope(country="US", state="OH", county="Franklin County"),
        priority=100,
    )

    def supports(self, jurisdiction: Jurisdiction, kind: SourceKind | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=[
                {
                    "instrument_number": "2025-0001",
                    "party_name": query.criteria["party_name"],
                }
            ],
        )


class _FakeHoaVendor:
    vendor_id = "fake-hoa-vendor"
    descriptor = VendorDescriptor(
        vendor_id=vendor_id,
        name="Fake HOA Vendor",
        kind=VendorKind.HOA_ESTOPPEL,
        jurisdiction_scopes=[JurisdictionScope(country="US", state="FL")],
        priority=100,
    )

    def supports(self, jurisdiction: Jurisdiction, kind: VendorKind | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and any(
            scope.matches(jurisdiction) for scope in self.descriptor.jurisdiction_scopes
        )

    async def submit_order(self, request: VendorOrderRequest) -> VendorOrderResult:
        return VendorOrderResult(
            vendor_id=self.vendor_id,
            status=VendorOrderStatus.SUBMITTED,
            external_order_id="vendor-123",
        )

    async def get_status(self, external_order_id: str) -> VendorOrderResult:
        return VendorOrderResult(
            vendor_id=self.vendor_id,
            status=VendorOrderStatus.IN_PROGRESS,
            external_order_id=external_order_id,
        )


if __name__ == "__main__":
    unittest.main()

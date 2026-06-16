from __future__ import annotations

# ruff: noqa: E501
import asyncio
import tomllib
import types
import unittest
from pathlib import Path

from titlemcp_us_oh_auditor.adapters import OhioCountyAuditorAdapter
from titlemcp_us_oh_auditor.manifest import capability_manifest
from titlemcp_us_oh_auditor.plugin import OhioAuditorPlugin
from titlemcp_us_oh_auditor.sites import CLERMONT, FRANKLIN, OH_IASWORLD_SITES
from titlemcp_us_oh_auditor.toolsets import OhioAuditorToolset

from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus
from title_mcp.sources.registry import SourceConnectorRegistry
from titlemcp_platform_iasworld import (
    AuditorSearchMode,
    IasWorldAuditorParcelDetail,
    IasWorldAuditorSearchHit,
    IasWorldAuditorSearchQuery,
    IasWorldAuditorSearchResponse,
    build_auditor_source_connector,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class OhioAuditorContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])

    def test_sites_table_includes_franklin(self) -> None:
        self.assertIn(FRANKLIN, OH_IASWORLD_SITES)
        self.assertEqual(FRANKLIN.source_id, "us-oh-franklin-auditor")
        self.assertEqual(FRANKLIN.district_code, "025")
        self.assertEqual(
            FRANKLIN.base_url,
            "https://property.franklincountyauditor.com/_web/",
        )
        self.assertTrue(FRANKLIN.numeric_parcel_ids)

    def test_sites_table_includes_clermont_with_alphanumeric_parcels(self) -> None:
        # A second county: config entry only, plus the one alphanumeric-parcel knob.
        self.assertIn(CLERMONT, OH_IASWORLD_SITES)
        self.assertEqual(CLERMONT.source_id, "us-oh-clermont-auditor")
        self.assertEqual(CLERMONT.district_code, "000")
        self.assertFalse(CLERMONT.numeric_parcel_ids)
        self.assertEqual(CLERMONT.tool_name, "clermont_county_auditor_search")

    def test_adapter_supports_ohio_tax_certificate(self) -> None:
        adapter = OhioCountyAuditorAdapter()

        self.assertTrue(
            adapter.supports(Jurisdiction(country="US", state="OH", county="Franklin County"))
        )
        self.assertFalse(
            adapter.supports(Jurisdiction(country="US", state="CA", county="Los Angeles County"))
        )
        self.assertIn(WorkflowKind.TAX_CERTIFICATE, adapter.workflow_kinds)

    def test_plugin_registers_one_source_per_county(self) -> None:
        registry = SourceConnectorRegistry()
        context = types.SimpleNamespace(sources=registry)

        OhioAuditorPlugin().register(context)

        for site in OH_IASWORLD_SITES:
            connector = registry.get(site.source_id)
            self.assertIsNotNone(connector)
            self.assertTrue(
                connector.supports(site.jurisdiction, SourceKind.TAX_AUTHORITY)
            )

    def test_toolset_registers_tool_per_county(self) -> None:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        OhioAuditorToolset().register(mcp, types.SimpleNamespace())

        tools = asyncio.run(mcp.list_tools())
        tool_names = {tool.name for tool in tools}
        for site in OH_IASWORLD_SITES:
            self.assertIn(site.tool_name, tool_names)
        self.assertIn("franklin_county_auditor_search", tool_names)

    def test_source_query_returns_canonical_record(self) -> None:
        connector = build_auditor_source_connector(FRANKLIN, client=_FakeClient())

        result = asyncio.run(
            connector.query(
                SourceQuery(
                    jurisdiction=FRANKLIN.jurisdiction,
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria={"mode": "parid", "parcel_id": "010-000123-00"},
                )
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        record = result.records[0]
        self.assertEqual(record["schema_name"], "title_mcp.property_assessment_record")
        self.assertEqual(record["source"]["source_id"], "us-oh-franklin-auditor")
        self.assertEqual(record["parcel"]["parcel_id"], "010-000123-00")
        self.assertEqual(record["tax_status"]["property_class"], "R - Residential")

    def test_missing_address_fields_report_failure_not_exception(self) -> None:
        # Address mode with no street should be caught and surfaced as FAILED.
        connector = build_auditor_source_connector(FRANKLIN, client=_FailingClient())

        result = asyncio.run(
            connector.query(
                SourceQuery(
                    jurisdiction=FRANKLIN.jurisdiction,
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria={"mode": "address"},
                )
            )
        )

        self.assertEqual(result.status, SourceResultStatus.FAILED)
        self.assertTrue(result.warnings)


class _FakeClient:
    def search(self, query: IasWorldAuditorSearchQuery) -> IasWorldAuditorSearchResponse:
        return IasWorldAuditorSearchResponse(
            query=query,
            search_url="https://example.test/search",
            search_mode=AuditorSearchMode.PARCEL_ID,
            result_count=1,
            results=[
                IasWorldAuditorSearchHit(
                    parcel_id="010-000123-00",
                    parcel_number="01000012300",
                    address="100 EXAMPLE AVE",
                    owner="DOE JANE A",
                )
            ],
            details=[
                IasWorldAuditorParcelDetail(
                    parcel_id="010-000123-00",
                    parcel_number="01000012300",
                    owners=["DOE JANE A"],
                    site_property_address="100 EXAMPLE AVE",
                    tax_status={"Property Class": "R - Residential"},
                )
            ],
        )


class _FailingClient:
    def search(self, query: IasWorldAuditorSearchQuery) -> IasWorldAuditorSearchResponse:
        raise RuntimeError("Address searches require street_name or address.")


if __name__ == "__main__":
    unittest.main()

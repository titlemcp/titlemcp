from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_platform_publicsearch import PublicSearchClient
from titlemcp_us_tx_recorder.adapters import TexasReleaseTrackingAdapter
from titlemcp_us_tx_recorder.manifest import capability_manifest
from titlemcp_us_tx_recorder.plugin import TexasRecorderPlugin
from titlemcp_us_tx_recorder.sites import (
    BEXAR,
    COLLIN,
    DALLAS,
    DENTON,
    HIDALGO,
    MONTGOMERY,
    TARRANT,
    TX_RECORDER_SITES,
)

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.capabilities.registry import CapabilityRegistry
from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
from title_mcp.domain.recorder import InstrumentKind
from title_mcp.plugins import PluginContext
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import MortgageReleaseSource, SourceKind
from title_mcp.sources.registry import SourceConnectorRegistry
from title_mcp.vendors.registry import VendorConnectorRegistry

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _context() -> PluginContext:
    return PluginContext(
        settings=TitleMCPSettings(),
        adapters=AdapterRegistry(),
        capabilities=CapabilityRegistry(),
        sources=SourceConnectorRegistry(),
        vendors=VendorConnectorRegistry(),
    )


class TexasRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(
            TX_RECORDER_SITES,
            (
                DALLAS,
                TARRANT,
                BEXAR,
                COLLIN,
                DENTON,
                HIDALGO,
                MONTGOMERY,
            ),
        )
        self.assertEqual(DALLAS.base_url, "https://dallas.tx.publicsearch.us")
        self.assertEqual({site.state for site in TX_RECORDER_SITES}, {"TX"})

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        TexasRecorderPlugin().register(context)

        for site in TX_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        county = Jurisdiction(state="TX", county="Dallas County")
        resolved = context.sources.resolve(county, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-tx-dallas-recorder")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        TexasRecorderPlugin().register(context)
        first = context.sources.get(DALLAS.source_id)

        TexasRecorderPlugin().register(context)

        self.assertIs(context.sources.get(DALLAS.source_id), first)


class TexasDocumentTypeTests(unittest.TestCase):
    def _kind(self, site, code: str, description: str) -> InstrumentKind:
        client = PublicSearchClient(site.base_url, document_type_kinds=site.document_type_kinds)
        row = {"docTypeCode": code, "docType": description, "instrumentNumber": "202600000001"}
        return client.to_instrument(row).kind

    def test_a_deed_of_trust_is_the_mortgage_in_every_county(self) -> None:
        for site in TX_RECORDER_SITES:
            with self.subTest(county=site.county):
                self.assertIs(self._kind(site, "DT", "DEED OF TRUST"), InstrumentKind.MORTGAGE)

    def test_counties_that_release_a_deed_of_trust_as_a_lien_say_so(self) -> None:
        self.assertIs(self._kind(DALLAS, "RE", "RELEASE OF LIEN"), InstrumentKind.RELEASE)
        self.assertIs(self._kind(DENTON, "RE", "RELEASE OF LIEN"), InstrumentKind.RELEASE)
        self.assertIs(self._kind(MONTGOMERY, "RLN", "RELEASE OF LIEN"), InstrumentKind.RELEASE)
        self.assertIs(
            self._kind(HIDALGO, "P/REL OF LIEN", "P/REL OF LIEN"),
            InstrumentKind.PARTIAL_RELEASE,
        )

    def test_other_liens_released_in_those_counties_stay_other(self) -> None:
        self.assertIs(self._kind(DALLAS, "RHL", "RELEASE OF HOSPITAL LIEN"), InstrumentKind.OTHER)
        self.assertIs(self._kind(DALLAS, "RLC", "RELEASE OF LIEN CLAIMED"), InstrumentKind.OTHER)

    def test_counties_that_write_release_need_no_correction(self) -> None:
        self.assertIs(self._kind(TARRANT, "R", "RELEASE"), InstrumentKind.RELEASE)
        self.assertIs(self._kind(COLLIN, "PREL", "PARTIAL RELEASE"), InstrumentKind.PARTIAL_RELEASE)
        self.assertIs(self._kind(BEXAR, "SAT", "SATISFACTION"), InstrumentKind.RELEASE)


class TexasReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_texas_only(self) -> None:
        adapter = TexasReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="TX", county="Dallas County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="OK", county="Tulsa County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="TX", county="Dallas County"),
        )

        plan = await TexasReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("343.108", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

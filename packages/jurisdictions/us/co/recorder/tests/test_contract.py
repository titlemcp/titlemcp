from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_co_recorder.adapters import ColoradoReleaseTrackingAdapter
from titlemcp_us_co_recorder.manifest import capability_manifest
from titlemcp_us_co_recorder.plugin import ColoradoRecorderPlugin
from titlemcp_us_co_recorder.sites import ARAPAHOE, CO_RECORDER_SITES

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.capabilities.registry import CapabilityRegistry
from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
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


class ColoradoRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(CO_RECORDER_SITES, (ARAPAHOE,))
        self.assertEqual(ARAPAHOE.base_url, "https://arapahoe.co.publicsearch.us")
        self.assertEqual({site.state for site in CO_RECORDER_SITES}, {"CO"})

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        ColoradoRecorderPlugin().register(context)

        for site in CO_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        county = Jurisdiction(state="CO", county="Arapahoe County")
        resolved = context.sources.resolve(county, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-co-arapahoe-recorder")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        ColoradoRecorderPlugin().register(context)
        first = context.sources.get(ARAPAHOE.source_id)

        ColoradoRecorderPlugin().register(context)

        self.assertIs(context.sources.get(ARAPAHOE.source_id), first)


class ColoradoReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_colorado_only(self) -> None:
        adapter = ColoradoReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="CO", county="Arapahoe County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="NM", county="Bernalillo County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="CO", county="Arapahoe County"),
        )

        plan = await ColoradoReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("38-35-124", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

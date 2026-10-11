from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_pa_recorder.adapters import PennsylvaniaReleaseTrackingAdapter
from titlemcp_us_pa_recorder.manifest import capability_manifest
from titlemcp_us_pa_recorder.plugin import PennsylvaniaRecorderPlugin
from titlemcp_us_pa_recorder.sites import DELAWARE, PA_RECORDER_SITES

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


class PennsylvaniaRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(PA_RECORDER_SITES, (DELAWARE,))
        self.assertEqual(DELAWARE.base_url, "https://delaware.pa.publicsearch.us")
        self.assertEqual({site.state for site in PA_RECORDER_SITES}, {"PA"})

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        PennsylvaniaRecorderPlugin().register(context)

        for site in PA_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        county = Jurisdiction(state="PA", county="Delaware County")
        resolved = context.sources.resolve(county, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-pa-delaware-recorder")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        PennsylvaniaRecorderPlugin().register(context)
        first = context.sources.get(DELAWARE.source_id)

        PennsylvaniaRecorderPlugin().register(context)

        self.assertIs(context.sources.get(DELAWARE.source_id), first)


class PennsylvaniaReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_pennsylvania_only(self) -> None:
        adapter = PennsylvaniaReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="PA", county="Delaware County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="OH", county="Delaware County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="PA", county="Delaware County"),
        )

        plan = await PennsylvaniaReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("721-6", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

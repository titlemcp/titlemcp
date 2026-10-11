from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_sc_recorder.adapters import SouthCarolinaReleaseTrackingAdapter
from titlemcp_us_sc_recorder.manifest import capability_manifest
from titlemcp_us_sc_recorder.plugin import SouthCarolinaRecorderPlugin
from titlemcp_us_sc_recorder.sites import GREENVILLE, SC_RECORDER_SITES

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


class SouthCarolinaRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(SC_RECORDER_SITES, (GREENVILLE,))
        self.assertEqual(GREENVILLE.base_url, "https://greenville.sc.publicsearch.us")
        self.assertEqual({site.state for site in SC_RECORDER_SITES}, {"SC"})

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        SouthCarolinaRecorderPlugin().register(context)

        for site in SC_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        county = Jurisdiction(state="SC", county="Greenville County")
        resolved = context.sources.resolve(county, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-sc-greenville-recorder")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        SouthCarolinaRecorderPlugin().register(context)
        first = context.sources.get(GREENVILLE.source_id)

        SouthCarolinaRecorderPlugin().register(context)

        self.assertIs(context.sources.get(GREENVILLE.source_id), first)


class SouthCarolinaReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_south_carolina_only(self) -> None:
        adapter = SouthCarolinaReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="SC", county="Greenville County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="NC", county="Guilford County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="SC", county="Greenville County"),
        )

        plan = await SouthCarolinaReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("29-3-310", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

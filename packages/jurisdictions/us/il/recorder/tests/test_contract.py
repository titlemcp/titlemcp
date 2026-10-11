from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_il_recorder.adapters import IllinoisReleaseTrackingAdapter
from titlemcp_us_il_recorder.manifest import capability_manifest
from titlemcp_us_il_recorder.plugin import IllinoisRecorderPlugin
from titlemcp_us_il_recorder.sites import IL_RECORDER_SITES, LAKE

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


class IllinoisRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(IL_RECORDER_SITES, (LAKE,))
        self.assertEqual(LAKE.base_url, "https://lake.il.publicsearch.us")
        self.assertEqual({site.state for site in IL_RECORDER_SITES}, {"IL"})

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        IllinoisRecorderPlugin().register(context)

        for site in IL_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        county = Jurisdiction(state="IL", county="Lake County")
        resolved = context.sources.resolve(county, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-il-lake-recorder")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        IllinoisRecorderPlugin().register(context)
        first = context.sources.get(LAKE.source_id)

        IllinoisRecorderPlugin().register(context)

        self.assertIs(context.sources.get(LAKE.source_id), first)


class IllinoisReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_illinois_only(self) -> None:
        adapter = IllinoisReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="IL", county="Lake County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="IN", county="Lake County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="IL", county="Lake County"),
        )

        plan = await IllinoisReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("905/4", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

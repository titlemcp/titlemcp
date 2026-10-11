from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_oh_recorder.adapters import OhioReleaseTrackingAdapter
from titlemcp_us_oh_recorder.manifest import capability_manifest
from titlemcp_us_oh_recorder.plugin import OhioRecorderPlugin
from titlemcp_us_oh_recorder.sites import (
    ASHLAND,
    CUYAHOGA,
    OH_COUNTYFUSION_SITES,
    OH_PUBLICSEARCH_SITES,
    OH_RECORDER_SITES,
    STARK,
    WAYNE,
)

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


class OhioRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.RELEASE_TRACKING, manifest.workflow_kinds)

    def test_sites_are_the_counties_on_publicsearch(self) -> None:
        self.assertEqual(OH_PUBLICSEARCH_SITES, (CUYAHOGA, STARK))
        self.assertEqual(CUYAHOGA.base_url, "https://cuyahoga.oh.publicsearch.us")
        self.assertEqual(STARK.base_url, "https://stark.oh.publicsearch.us")
        self.assertEqual({site.state for site in OH_PUBLICSEARCH_SITES}, {"OH"})

    def test_sites_are_the_counties_on_countyfusion(self) -> None:
        self.assertEqual(OH_COUNTYFUSION_SITES, (WAYNE, ASHLAND))
        self.assertEqual(WAYNE.base_url, "https://countyfusion8.kofiletech.us/countyweb")
        self.assertEqual((WAYNE.county_key, ASHLAND.county_key), ("WayneOH", "AshlandOH"))

    def test_the_plugin_registers_a_release_source_per_county(self) -> None:
        context = _context()

        OhioRecorderPlugin().register(context)

        for site in OH_RECORDER_SITES:
            connector = context.sources.get(site.source_id)
            self.assertIsInstance(connector, MortgageReleaseSource)
        cuyahoga = Jurisdiction(state="OH", county="Cuyahoga County")
        resolved = context.sources.resolve(cuyahoga, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.source_id, "us-oh-cuyahoga-recorder")
        wayne = Jurisdiction(state="OH", county="Wayne County")
        resolved = context.sources.resolve(wayne, SourceKind.COUNTY_RECORDER)
        self.assertEqual(resolved.descriptor.metadata["platform"], "kofile-countyfusion")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        OhioRecorderPlugin().register(context)
        first = context.sources.get(CUYAHOGA.source_id)

        OhioRecorderPlugin().register(context)

        self.assertIs(context.sources.get(CUYAHOGA.source_id), first)


class OhioReleaseTrackingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_ohio_only(self) -> None:
        adapter = OhioReleaseTrackingAdapter()

        self.assertTrue(adapter.supports(Jurisdiction(state="OH", county="Wayne County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="PA", county="Erie County")))

    async def test_the_plan_checks_the_record_before_the_lender(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.RELEASE_TRACKING,
            jurisdiction=Jurisdiction(state="OH", county="Cuyahoga County"),
        )

        plan = await OhioReleaseTrackingAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "mortgage_release_search")
        self.assertIn("5301.36", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

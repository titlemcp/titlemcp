from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_va_tax.adapters import VirginiaTaxCertificateAdapter
from titlemcp_us_va_tax.manifest import capability_manifest
from titlemcp_us_va_tax.plugin import VirginiaTaxPlugin
from titlemcp_us_va_tax.sites import FAIRFAX, VA_TAX_SITES

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.capabilities.registry import CapabilityRegistry
from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
from title_mcp.plugins import PluginContext
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import PropertyTaxSource, SourceKind
from title_mcp.sources.registry import SourceConnectorRegistry
from title_mcp.vendors.registry import VendorConnectorRegistry
from titlemcp_platform_iasworld import TaxPage

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
COUNTY = Jurisdiction(state="VA", county="Fairfax County")


def _context() -> PluginContext:
    return PluginContext(
        settings=TitleMCPSettings(),
        adapters=AdapterRegistry(),
        capabilities=CapabilityRegistry(),
        sources=SourceConnectorRegistry(),
        vendors=VendorConnectorRegistry(),
    )


class VirginiaTaxContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.TAX_CERTIFICATE, manifest.workflow_kinds)

    def test_sites_are_the_counties_read_for_tax(self) -> None:
        self.assertEqual(VA_TAX_SITES, (FAIRFAX,))
        self.assertEqual(FAIRFAX.base_url, "https://icare.fairfaxcounty.gov/ffxcare/")
        self.assertIsNot(FAIRFAX.tax_page, TaxPage.AUDITOR)
        self.assertEqual({site.state for site in VA_TAX_SITES}, {"VA"})

    def test_the_plugin_registers_a_tax_source_per_county(self) -> None:
        context = _context()

        VirginiaTaxPlugin().register(context)

        connector = context.sources.get(FAIRFAX.source_id)
        self.assertIsInstance(connector, PropertyTaxSource)
        resolved = context.sources.resolve(COUNTY, SourceKind.TAX_AUTHORITY)
        self.assertEqual(resolved.source_id, "us-va-fairfax-tax")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        VirginiaTaxPlugin().register(context)
        first = context.sources.get(FAIRFAX.source_id)

        VirginiaTaxPlugin().register(context)

        self.assertIs(context.sources.get(FAIRFAX.source_id), first)


class VirginiaTaxCertificateAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_the_configured_counties_only(self) -> None:
        adapter = VirginiaTaxCertificateAdapter()

        self.assertTrue(adapter.supports(COUNTY))
        self.assertFalse(adapter.supports(Jurisdiction(state="VA", county="Sample County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="OH", county="Fairfax County")))

    async def test_the_plan_reads_the_county_before_confirming_the_payoff(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.TAX_CERTIFICATE,
            jurisdiction=COUNTY,
        )

        plan = await VirginiaTaxCertificateAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "property_tax_status_search")


if __name__ == "__main__":
    unittest.main()

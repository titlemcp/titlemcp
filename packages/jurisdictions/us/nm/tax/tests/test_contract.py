from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_nm_tax.adapters import NewMexicoTaxCertificateAdapter
from titlemcp_us_nm_tax.manifest import capability_manifest
from titlemcp_us_nm_tax.plugin import NewMexicoTaxPlugin
from titlemcp_us_nm_tax.sites import BERNALILLO, NM_TAX_SITES

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
COUNTY = Jurisdiction(state="NM", county="Bernalillo County")


def _context() -> PluginContext:
    return PluginContext(
        settings=TitleMCPSettings(),
        adapters=AdapterRegistry(),
        capabilities=CapabilityRegistry(),
        sources=SourceConnectorRegistry(),
        vendors=VendorConnectorRegistry(),
    )


class NewMexicoTaxContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.TAX_CERTIFICATE, manifest.workflow_kinds)

    def test_sites_are_the_counties_read_for_tax(self) -> None:
        self.assertEqual(NM_TAX_SITES, (BERNALILLO,))
        self.assertEqual(BERNALILLO.base_url, "https://treasurer.bernco.gov/public.access/")
        self.assertIsNot(BERNALILLO.tax_page, TaxPage.AUDITOR)
        self.assertEqual({site.state for site in NM_TAX_SITES}, {"NM"})

    def test_the_plugin_registers_a_tax_source_per_county(self) -> None:
        context = _context()

        NewMexicoTaxPlugin().register(context)

        connector = context.sources.get(BERNALILLO.source_id)
        self.assertIsInstance(connector, PropertyTaxSource)
        resolved = context.sources.resolve(COUNTY, SourceKind.TAX_AUTHORITY)
        self.assertEqual(resolved.source_id, "us-nm-bernalillo-tax")

    def test_a_connector_already_registered_is_kept(self) -> None:
        context = _context()
        NewMexicoTaxPlugin().register(context)
        first = context.sources.get(BERNALILLO.source_id)

        NewMexicoTaxPlugin().register(context)

        self.assertIs(context.sources.get(BERNALILLO.source_id), first)


class NewMexicoTaxCertificateAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_it_covers_the_configured_counties_only(self) -> None:
        adapter = NewMexicoTaxCertificateAdapter()

        self.assertTrue(adapter.supports(COUNTY))
        self.assertFalse(adapter.supports(Jurisdiction(state="NM", county="Sample County")))
        self.assertFalse(adapter.supports(Jurisdiction(state="OH", county="Bernalillo County")))

    async def test_the_plan_reads_the_county_before_confirming_the_payoff(self) -> None:
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.TAX_CERTIFICATE,
            jurisdiction=COUNTY,
        )

        plan = await NewMexicoTaxCertificateAdapter().plan(request)

        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "property_tax_status_search")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

# ruff: noqa: E501
import tomllib
import unittest
from pathlib import Path

from titlemcp_us_oh_franklin_recorder.adapters import FranklinCountyOhioRecorderAdapter
from titlemcp_us_oh_franklin_recorder.auditor import (
    AuditorSearchMode,
    FranklinAuditorClient,
    FranklinAuditorSearchQuery,
    FranklinAuditorSearchResponse,
    resolve_auditor_search_mode,
)
from titlemcp_us_oh_franklin_recorder.manifest import capability_manifest
from titlemcp_us_oh_franklin_recorder.sources import (
    FranklinAuditorSourceConnector,
    FranklinRecorderSourceConnector,
)

from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class FranklinRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])

    def test_adapter_supports_franklin_county_public_records(self) -> None:
        adapter = FranklinCountyOhioRecorderAdapter()

        self.assertTrue(
            adapter.supports(Jurisdiction(country="US", state="OH", county="Franklin County"))
        )
        self.assertIn(WorkflowKind.PUBLIC_RECORDS_SEARCH, adapter.workflow_kinds)

    def test_source_supports_franklin_county_recorder(self) -> None:
        source = FranklinRecorderSourceConnector(websocket_url="wss://example.invalid")

        self.assertTrue(
            source.supports(
                Jurisdiction(country="US", state="OH", county="Franklin County"),
                SourceKind.COUNTY_RECORDER,
            )
        )

    def test_source_supports_franklin_county_auditor(self) -> None:
        source = FranklinAuditorSourceConnector(client=_FakeAuditorClient())

        self.assertTrue(
            source.supports(
                Jurisdiction(country="US", state="OH", county="Franklin County"),
                SourceKind.TAX_AUTHORITY,
            )
        )

    def test_auditor_search_result_parser_extracts_rows(self) -> None:
        client = FranklinAuditorClient()

        rows = client._parse_search_results(SEARCH_RESULT_HTML)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].parcel_id, "030-000526-00")
        self.assertEqual(rows[0].parcel_number, "03000052600")
        self.assertEqual(rows[0].parcel_token, "025:03000052600:2026")
        self.assertEqual(rows[0].jurisdiction, "025")
        self.assertEqual(rows[0].tax_year, "2026")
        self.assertEqual(rows[0].address, "1150 GLENN AVE")
        self.assertEqual(rows[0].owner, "ZWINK ROBERT V")

    def test_auditor_detail_parser_returns_structured_sections(self) -> None:
        client = FranklinAuditorClient()

        detail = client.parse_detail(DETAIL_HTML, source_url="https://example.test/detail")

        self.assertEqual(detail.parcel_id, "030-000526-00")
        self.assertEqual(detail.parcel_number, "03000052600")
        self.assertEqual(detail.map_routing, "030-M065-09800")
        self.assertEqual(detail.owners, ["ZWINK ROBERT V", "ZWINK KELLY K"])
        self.assertEqual(detail.site_property_address, "1150 GLENN AVE")
        self.assertEqual(detail.legal_description[-1], "LOT 193 & 30' NS LOT 194 & PT VAC AL")
        self.assertEqual(detail.most_recent_transfer["Transfer Price"], "$750,000")
        self.assertEqual(detail.tax_status["Property Class"], "R - Residential")
        self.assertEqual(
            detail.appraised_value["rows"][0],
            {
                "": "Base",
                "Land": "290,900",
                "Improvements": "427,600",
                "Total": "718,500",
            },
        )

    def test_auditor_source_query_returns_structured_record(self) -> None:
        source = FranklinAuditorSourceConnector(client=_FakeAuditorClient())

        result = self.run_async(
            source.query(
                SourceQuery(
                    jurisdiction=Jurisdiction(country="US", state="OH", county="Franklin County"),
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria={"mode": "parid", "parcel_id": "030-000526-00"},
                )
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        record = result.records[0]
        self.assertEqual(record["schema_name"], "title_mcp.property_assessment_record")
        self.assertEqual(record["record_type"], "property_assessment")
        self.assertEqual(record["parcel"]["parcel_id"], "030-000526-00")
        self.assertEqual(record["parcel"]["parcel_number"], "03000052600")
        self.assertEqual(record["ownership"]["owners"], ["ZWINK ROBERT V", "ZWINK KELLY K"])
        self.assertEqual(record["property"]["site_address_display"], "1150 GLENN AVE")
        self.assertEqual(record["tax_status"]["property_class"], "R - Residential")
        self.assertEqual(
            record["valuation"]["appraised"]["summary"]["base"]["total"]["display"],
            "718,500",
        )
        self.assertEqual(
            record["taxes"]["annual"][0]["net_annual_tax"]["display"],
            "14,667.70",
        )
        self.assertEqual(
            record["source_specific"]["franklin_auditor"]["detail"]["parcel_number"],
            "03000052600",
        )

    def test_auditor_search_mode_infers_from_search_fields(self) -> None:
        self.assertEqual(
            resolve_auditor_search_mode("structured_data", parcel_id="030-000526-00"),
            AuditorSearchMode.PARCEL_ID,
        )
        self.assertEqual(
            resolve_auditor_search_mode(None, owner_name="ZWINK ROBERT V"),
            AuditorSearchMode.OWNER,
        )
        self.assertEqual(
            resolve_auditor_search_mode(None, address="1150 GLENN AVE"),
            AuditorSearchMode.ADDRESS,
        )

    @staticmethod
    def run_async(coro):
        import asyncio

        return asyncio.run(coro)


SEARCH_RESULT_HTML = """
<table id="searchResults">
  <tr class="SearchResults"
      onclick="javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=1')">
    <td><input name="chkPin" value="025:03000052600:2026"></td>
    <td><input type="hidden" id="parid" value="025:03000052600:2026"></td>
    <td><div>030-000526-00</div></td>
    <td><div>1150 GLENN AVE</div></td>
    <td><div>ZWINK ROBERT V</div></td>
    <td><div>F.S. WAGEN(T)HALS ET AL'S AMENDED SUBDIVISION</div></td>
  </tr>
</table>
"""


DETAIL_HTML = """
<table class="DataletHeader">
  <tr>
    <td>Parcel ID: 030-000526-00</td>
    <td>Map Routing: 030-M065-09800</td>
  </tr>
  <tr>
    <td>ZWINK ROBERT V</td>
    <td>1150 GLENN AVE</td>
  </tr>
</table>
<table id="Owner">
  <tr><td class="DataletSideHeading">Owner</td><td class="DataletData">ZWINK ROBERT V</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">ZWINK KELLY K</td></tr>
  <tr><td class="DataletSideHeading">Owner Mailing /</td><td class="DataletData">1150 GLENN AVE</td></tr>
  <tr><td class="DataletSideHeading">Contact Address</td><td class="DataletData">COLUMBUS OH 43212 3230</td></tr>
  <tr><td class="DataletSideHeading">Site (Property) Address</td><td class="DataletData">1150 GLENN AVE</td></tr>
  <tr><td class="DataletSideHeading">Legal Description</td><td class="DataletData">F.S. WAGEN(T)HALS ET AL'S AMENDED SUBDIVISION</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">OF LOTS IN J.R. TILTON'S GLADDINGTON HEIGHTS SUBDIVISION</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">LOT 193 &amp; 30' NS LOT 194 &amp; PT VAC AL</td></tr>
  <tr><td class="DataletSideHeading">Legal Acres</td><td class="DataletData">0</td></tr>
  <tr><td class="DataletSideHeading">Parcel Permalink</td><td class="DataletData">https://audr-apps.franklincountyohio.gov/redir/Link/Parcel/03000052600</td></tr>
</table>
<table id="Most Recent Transfer">
  <tr><td>Transfer Date</td><td>APR-09-2021</td></tr>
  <tr><td>Transfer Price</td><td>$750,000</td></tr>
  <tr><td>Instrument Type</td><td>SU</td></tr>
  <tr><td>Parcel Count</td><td>1</td></tr>
</table>
<table id="2025 Tax Status">
  <tr><td>Property Class</td><td>R - Residential</td></tr>
  <tr><td>Land Use</td><td>510 - ONE-FAM DWLG ON PLATTED LOT</td></tr>
</table>
<table id="2025 Auditor">
  <tr><td></td><td>Land</td><td>Improvements</td><td>Total</td></tr>
  <tr><td>Base</td><td>290,900</td><td>427,600</td><td>718,500</td></tr>
</table>
<table id="Annual Taxes">
  <tr><td>Tax Year</td><td>Net Annual Tax</td><td>Total Paid</td></tr>
  <tr><td>2025</td><td>14,667.70</td><td>7,333.85</td></tr>
</table>
<input type="hidden" id="hdPin" value="03000052600" />
<input type="hidden" id="hdTaxYear" value="2026" />
<input type="hidden" id="hdJur" value="025" />
"""


class _FakeAuditorClient:
    def search(self, query: FranklinAuditorSearchQuery) -> FranklinAuditorSearchResponse:
        client = FranklinAuditorClient()
        detail = client.parse_detail(DETAIL_HTML, source_url="https://example.test/detail")
        hit = client._parse_search_results(SEARCH_RESULT_HTML)[0]
        return FranklinAuditorSearchResponse(
            query=query,
            search_url="https://example.test/search",
            search_mode=AuditorSearchMode.PARCEL_ID,
            result_count=1,
            results=[hit],
            details=[detail],
        )


if __name__ == "__main__":
    unittest.main()

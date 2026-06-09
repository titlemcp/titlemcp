from __future__ import annotations

# ruff: noqa: E501
import asyncio
import unittest

from title_mcp.domain.models import Jurisdiction
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus
from titlemcp_platform_iasworld import (
    AuditorSearchMode,
    DetailProfile,
    IasWorldAuditorClient,
    IasWorldAuditorSearchQuery,
    IasWorldAuditorSearchResponse,
    IasWorldSiteConfig,
    build_auditor_source_connector,
)

FRANKLIN = IasWorldSiteConfig(
    source_id="us-oh-franklin-auditor",
    county="Franklin County",
    state="OH",
    name="Franklin County, Ohio Auditor Property Search",
    base_url="https://property.franklincountyauditor.com/_web/",
    district_code="025",
)

CLERMONT = IasWorldSiteConfig(
    source_id="us-oh-clermont-auditor",
    county="Clermont County",
    state="OH",
    name="Clermont County, Ohio Auditor Property Search",
    base_url="https://www.clermontauditorrealestate.org/_web/",
    district_code="000",
    numeric_parcel_ids=False,
    detail_profile=DetailProfile.PUBLIC_ACCESS,
)


class IasWorldClientTests(unittest.TestCase):
    def test_search_result_parser_extracts_rows(self) -> None:
        client = IasWorldAuditorClient(FRANKLIN)

        rows = client._parse_search_results(SEARCH_RESULT_HTML)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].parcel_id, "010-000123-00")
        self.assertEqual(rows[0].parcel_number, "01000012300")
        self.assertEqual(rows[0].parcel_token, "025:01000012300:2026")
        self.assertEqual(rows[0].jurisdiction, "025")
        self.assertEqual(rows[0].tax_year, "2026")
        self.assertEqual(rows[0].address, "100 EXAMPLE AVE")
        self.assertEqual(rows[0].owner, "DOE JANE A")

    def test_detail_parser_returns_structured_sections(self) -> None:
        client = IasWorldAuditorClient(FRANKLIN)

        detail = client.parse_detail(DETAIL_HTML, source_url="https://example.test/detail")

        self.assertEqual(detail.parcel_id, "010-000123-00")
        self.assertEqual(detail.parcel_number, "01000012300")
        self.assertEqual(detail.map_routing, "010-X000-00000")
        self.assertEqual(detail.owners, ["DOE JANE A", "DOE JOHN Q"])
        self.assertEqual(detail.site_property_address, "100 EXAMPLE AVE")
        self.assertEqual(detail.legal_description[-1], "LOT 1 & PT LOT 2")
        self.assertEqual(detail.most_recent_transfer["Transfer Price"], "$500,000")
        self.assertEqual(detail.tax_status["Property Class"], "R - Residential")
        self.assertEqual(
            detail.appraised_value["rows"][0],
            {"": "Base", "Land": "100,000", "Improvements": "200,000", "Total": "300,000"},
        )


class IasWorldConfigTests(unittest.TestCase):
    def test_search_and_detail_urls_use_base_url_and_district(self) -> None:
        client = IasWorldAuditorClient(FRANKLIN)

        self.assertEqual(
            FRANKLIN.search_url(AuditorSearchMode.ADDRESS),
            "https://property.franklincountyauditor.com/_web/search/commonsearch.aspx?mode=address",
        )
        detail_url = client.detail_url(parcel_number="010-000123-00")
        self.assertIn("property.franklincountyauditor.com/_web/Datalets/Datalet.aspx", detail_url)
        self.assertIn("jur=025", detail_url)
        self.assertIn("pin=01000012300", detail_url)

    def test_bare_domain_base_url_gets_trailing_slash(self) -> None:
        montgomery = IasWorldSiteConfig(
            source_id="us-oh-montgomery-auditor",
            county="Montgomery County",
            state="OH",
            name="Montgomery County, Ohio Auditor",
            base_url="https://www.mcrealestate.org",  # no trailing slash, no /_web/
            district_code="000",
        )

        self.assertEqual(
            montgomery.search_url(AuditorSearchMode.PARCEL_ID),
            "https://www.mcrealestate.org/search/commonsearch.aspx?mode=parid",
        )
        detail_url = IasWorldAuditorClient(montgomery).detail_url(parcel_number="R72 00107 0001")
        self.assertIn("www.mcrealestate.org/Datalets/Datalet.aspx", detail_url)
        self.assertIn("jur=000", detail_url)

    def test_mode_map_overrides_url_mode_for_realprop_sites(self) -> None:
        summit = IasWorldSiteConfig(
            source_id="us-oh-summit-auditor",
            county="Summit County",
            state="OH",
            name="Summit County, Ohio Fiscal Office",
            base_url="https://propertyaccess.summitoh.net/",
            district_code="000",
            mode_map={AuditorSearchMode.ADDRESS: "realprop"},
        )

        self.assertEqual(
            summit.search_url(AuditorSearchMode.ADDRESS),
            "https://propertyaccess.summitoh.net/search/commonsearch.aspx?mode=realprop",
        )
        # Non-overridden modes still fall back to the enum value.
        self.assertEqual(
            summit.search_url(AuditorSearchMode.OWNER),
            "https://propertyaccess.summitoh.net/search/commonsearch.aspx?mode=owner",
        )

    def test_tool_name_and_title_derived_from_county(self) -> None:
        self.assertEqual(FRANKLIN.tool_name, "franklin_county_auditor_search")
        self.assertEqual(FRANKLIN.tool_title, "Franklin County Auditor Search")


class IasWorldCanonicalTests(unittest.TestCase):
    def test_source_connector_maps_to_canonical_record(self) -> None:
        connector = build_auditor_source_connector(FRANKLIN, client=_FakeClient())

        result = asyncio.run(
            connector.query(
                SourceQuery(
                    jurisdiction=Jurisdiction(country="US", state="OH", county="Franklin County"),
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria={"mode": "parid", "parcel_id": "010-000123-00"},
                )
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        record = result.records[0]
        self.assertEqual(record["schema_name"], "title_mcp.property_assessment_record")
        self.assertEqual(record["record_type"], "property_assessment")
        self.assertEqual(record["parcel"]["parcel_id"], "010-000123-00")
        self.assertEqual(record["ownership"]["owners"], ["DOE JANE A", "DOE JOHN Q"])
        self.assertEqual(record["property"]["site_address_display"], "100 EXAMPLE AVE")
        self.assertEqual(record["tax_status"]["property_class"], "R - Residential")
        self.assertEqual(
            record["valuation"]["appraised"]["summary"]["base"]["total"]["display"],
            "300,000",
        )
        self.assertEqual(record["taxes"]["annual"][0]["net_annual_tax"]["display"], "5,000.00")
        self.assertEqual(
            record["source_specific"]["iasworld_auditor"]["detail"]["parcel_number"],
            "01000012300",
        )

    def test_connector_supports_tax_authority_kind(self) -> None:
        connector = build_auditor_source_connector(FRANKLIN, client=_FakeClient())

        self.assertTrue(
            connector.supports(
                Jurisdiction(country="US", state="OH", county="Franklin County"),
                SourceKind.TAX_AUTHORITY,
            )
        )


SEARCH_RESULT_HTML = """
<table id="searchResults">
  <tr class="SearchResults"
      onclick="javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=1')">
    <td><input name="chkPin" value="025:01000012300:2026"></td>
    <td><input type="hidden" id="parid" value="025:01000012300:2026"></td>
    <td><div>010-000123-00</div></td>
    <td><div>100 EXAMPLE AVE</div></td>
    <td><div>DOE JANE A</div></td>
    <td><div>EXAMPLE HEIGHTS SUBDIVISION</div></td>
  </tr>
</table>
"""


DETAIL_HTML = """
<table class="DataletHeader">
  <tr>
    <td>Parcel ID: 010-000123-00</td>
    <td>Map Routing: 010-X000-00000</td>
  </tr>
  <tr>
    <td>DOE JANE A</td>
    <td>100 EXAMPLE AVE</td>
  </tr>
</table>
<table id="Owner">
  <tr><td class="DataletSideHeading">Owner</td><td class="DataletData">DOE JANE A</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">DOE JOHN Q</td></tr>
  <tr><td class="DataletSideHeading">Owner Mailing /</td><td class="DataletData">100 EXAMPLE AVE</td></tr>
  <tr><td class="DataletSideHeading">Contact Address</td><td class="DataletData">COLUMBUS OH 43200 0000</td></tr>
  <tr><td class="DataletSideHeading">Site (Property) Address</td><td class="DataletData">100 EXAMPLE AVE</td></tr>
  <tr><td class="DataletSideHeading">Legal Description</td><td class="DataletData">EXAMPLE HEIGHTS SUBDIVISION</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">OF LOTS IN SAMPLE PLACE NO 2</td></tr>
  <tr><td class="DataletSideHeading">&nbsp;</td><td class="DataletData">LOT 1 &amp; PT LOT 2</td></tr>
  <tr><td class="DataletSideHeading">Legal Acres</td><td class="DataletData">0</td></tr>
  <tr><td class="DataletSideHeading">Parcel Permalink</td><td class="DataletData">https://example.test/parcel/01000012300</td></tr>
</table>
<table id="Most Recent Transfer">
  <tr><td>Transfer Date</td><td>JAN-01-2020</td></tr>
  <tr><td>Transfer Price</td><td>$500,000</td></tr>
  <tr><td>Instrument Type</td><td>SU</td></tr>
  <tr><td>Parcel Count</td><td>1</td></tr>
</table>
<table id="2025 Tax Status">
  <tr><td>Property Class</td><td>R - Residential</td></tr>
  <tr><td>Land Use</td><td>510 - ONE-FAM DWLG ON PLATTED LOT</td></tr>
</table>
<table id="2025 Auditor">
  <tr><td></td><td>Land</td><td>Improvements</td><td>Total</td></tr>
  <tr><td>Base</td><td>100,000</td><td>200,000</td><td>300,000</td></tr>
</table>
<table id="Annual Taxes">
  <tr><td>Tax Year</td><td>Net Annual Tax</td><td>Total Paid</td></tr>
  <tr><td>2025</td><td>5,000.00</td><td>2,500.00</td></tr>
</table>
<input type="hidden" id="hdPin" value="01000012300" />
<input type="hidden" id="hdTaxYear" value="2026" />
<input type="hidden" id="hdJur" value="025" />
"""


class _FakeClient:
    """Returns parsed Franklin fixtures without touching the network."""

    def search(self, query: IasWorldAuditorSearchQuery) -> IasWorldAuditorSearchResponse:
        client = IasWorldAuditorClient(FRANKLIN)
        detail = client.parse_detail(DETAIL_HTML, source_url="https://example.test/detail")
        hit = client._parse_search_results(SEARCH_RESULT_HTML)[0]
        return IasWorldAuditorSearchResponse(
            query=query,
            search_url="https://example.test/search",
            search_mode=AuditorSearchMode.PARCEL_ID,
            result_count=1,
            results=[hit],
            details=[detail],
        )


class IasWorldAlphanumericParcelTests(unittest.TestCase):
    """A second county (Clermont) reuses the whole scraper; only one knob differs."""

    def test_compaction_respects_numeric_only_flag(self) -> None:
        from titlemcp_platform_iasworld.client import _compact_parcel_id

        # Numeric (Franklin default) strips the letters; alphanumeric preserves them.
        self.assertEqual(_compact_parcel_id("100200C003D"), "100200003")
        self.assertEqual(_compact_parcel_id("100200C003D", numeric_only=False), "100200C003D")
        self.assertEqual(_compact_parcel_id("100200.034C", numeric_only=False), "100200.034C")
        self.assertEqual(_compact_parcel_id("10-02-00C-003", numeric_only=False), "100200C003")

    def test_clermont_search_preserves_alphanumeric_parcel(self) -> None:
        client = IasWorldAuditorClient(CLERMONT)

        rows = client._parse_search_results(CLERMONT_SEARCH_HTML)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].parcel_number, "100200C003D")  # not mangled to 100200003
        self.assertEqual(rows[0].parcel_token, "000:100200C003D:2025")
        self.assertEqual(rows[0].jurisdiction, "000")
        self.assertEqual(rows[0].owner, "DOE JANE A TRUSTEE")

    def test_clermont_detail_url_keeps_pin_and_district(self) -> None:
        url = IasWorldAuditorClient(CLERMONT).detail_url(parcel_number="100200.034C")

        self.assertIn("www.clermontauditorrealestate.org/_web/Datalets/Datalet.aspx", url)
        self.assertIn("pin=100200.034C", url)
        self.assertIn("jur=000", url)

    def test_franklin_numeric_config_would_mangle_a_clermont_pin(self) -> None:
        # Contrast that proves the knob matters: the numeric default drops letters.
        url = IasWorldAuditorClient(FRANKLIN).detail_url(parcel_number="100200C003D")

        self.assertIn("pin=100200003", url)

    def test_public_access_detail_parses_split_sections(self) -> None:
        detail = IasWorldAuditorClient(CLERMONT).parse_detail(CLERMONT_DETAIL_HTML)

        self.assertEqual(detail.parcel_number, "100200C003D")
        self.assertEqual(detail.jurisdiction, "000")
        self.assertEqual(detail.owners, ["DOE JANE A TRUSTEE"])
        self.assertEqual(detail.site_property_address, "100 EXAMPLE DR")
        self.assertEqual(detail.owner_mailing_address, ["100 EXAMPLE DR", "ANYTOWN OH 45000"])
        self.assertEqual(detail.legal_description, ["EXAMPLE CITY SUBDIVISION LOT 1"])
        # Public Access labels normalized into the same keys the classic profile uses.
        self.assertEqual(detail.tax_status["Property Class"], "RESIDENTIAL")
        self.assertEqual(detail.tax_status["Land Use"], "510-R - SINGLE FAMILY DWELLING, PLATTED LOT")

    def test_clermont_detail_maps_to_canonical_record(self) -> None:
        connector = build_auditor_source_connector(CLERMONT, client=_ClermontFakeClient())

        result = asyncio.run(
            connector.query(
                SourceQuery(
                    jurisdiction=CLERMONT.jurisdiction,
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria={"mode": "parid", "parcel_id": "100200C003D"},
                )
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        record = result.records[0]
        self.assertEqual(record["source"]["source_id"], "us-oh-clermont-auditor")
        self.assertEqual(record["jurisdiction"]["county"], "Clermont County")
        self.assertEqual(record["parcel"]["parcel_number"], "100200C003D")
        self.assertEqual(record["ownership"]["owners"], ["DOE JANE A TRUSTEE"])
        self.assertEqual(record["property"]["site_address_display"], "100 EXAMPLE DR")
        self.assertEqual(record["property"]["legal_description_text"], "EXAMPLE CITY SUBDIVISION LOT 1")
        self.assertEqual(record["tax_status"]["property_class"], "RESIDENTIAL")
        self.assertEqual(record["taxes"]["annual"][0]["net_annual_tax"]["display"], "$5,000.00")


# Synthetic Clermont markup (fake owner/parcel/address) structured like the live
# iasWorld "Public Access" datalet — its section names/labels differ from
# Franklin's classic datalet, which is what these tests exercise.
CLERMONT_SEARCH_HTML = """
<table id="searchResults">
  <tr class="SearchResults"
      onclick="javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=1')">
    <td><input name="chkPin" value="000:100200C003D:2025"></td>
    <td><div>100200C003D</div></td>
    <td><div>100 EXAMPLE DR</div></td>
    <td><div>DOE JANE A TRUSTEE</div></td>
    <td><div>EXAMPLE CITY SUBDIVISION LOT 1</div></td>
  </tr>
</table>
"""


CLERMONT_DETAIL_HTML = """
<table id="Parcel">
  <tr><td>Address</td><td>100 EXAMPLE DR</td></tr>
  <tr><td>Unit #</td><td></td></tr>
  <tr><td>Class</td><td>RESIDENTIAL</td></tr>
  <tr><td>Land Use Code</td><td>510-R - SINGLE FAMILY DWELLING, PLATTED LOT</td></tr>
  <tr><td>Tax Roll</td><td>RP_OH</td></tr>
  <tr><td>Neighborhood</td><td>00500R10</td></tr>
  <tr><td>Total Acres</td><td>.5000</td></tr>
</table>
<table id="Owner">
  <tr><td>Owner 1</td><td>DOE JANE A TRUSTEE</td></tr>
  <tr><td>Owner 2</td><td></td></tr>
</table>
<table id="Tax Mailing Name and Address">
  <tr><td>Mailing Name 1</td><td>DOE JANE A TRUSTEE</td></tr>
  <tr><td>Mailing Name 2</td><td></td></tr>
  <tr><td>Address 1</td><td>100 EXAMPLE DR</td></tr>
  <tr><td>Address 2</td><td></td></tr>
  <tr><td>Address 3</td><td>ANYTOWN OH 45000</td></tr>
</table>
<table id="Legal">
  <tr><td>Legal Desc 1</td><td>EXAMPLE CITY SUBDIVISION LOT 1</td></tr>
  <tr><td>Legal Desc 2</td><td></td></tr>
</table>
<table id="Taxes Charged">
  <tr><td>Tax Roll</td><td>Delq Taxes</td><td>1ST Taxes</td><td>2ND Taxes</td><td>Total Charged</td></tr>
  <tr><td>RP_OH</td><td>$0.00</td><td>$2,500.00</td><td>$2,500.00</td><td>$5,000.00</td></tr>
</table>
<table id="Taxes Due">
  <tr><td>Tax Roll</td><td>Delq Taxes</td><td>1ST Taxes</td><td>2ND Taxes</td><td>Total Due</td></tr>
  <tr><td>RP_OH</td><td>$0.00</td><td>$0.00</td><td>$2,500.00</td><td>$2,500.00</td></tr>
</table>
<table id="Homestead Credits">
  <tr><td>Homestead Exemption</td><td>NO</td></tr>
  <tr><td>Owner Occupancy Credit</td><td>YES</td></tr>
</table>
<input type="hidden" id="hdPin" value="100200C003D" />
<input type="hidden" id="hdTaxYear" value="2025" />
<input type="hidden" id="hdJur" value="000" />
"""


class _ClermontFakeClient:
    def search(self, query: IasWorldAuditorSearchQuery) -> IasWorldAuditorSearchResponse:
        client = IasWorldAuditorClient(CLERMONT)
        detail = client.parse_detail(CLERMONT_DETAIL_HTML, source_url="https://example.test/clermont")
        hit = client._parse_search_results(CLERMONT_SEARCH_HTML)[0]
        return IasWorldAuditorSearchResponse(
            query=query,
            search_url="https://example.test/search",
            search_mode=AuditorSearchMode.PARCEL_ID,
            result_count=1,
            results=[hit],
            details=[detail],
        )


if __name__ == "__main__":
    unittest.main()

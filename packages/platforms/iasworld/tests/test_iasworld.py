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


class IasWorldNewerBuildTests(unittest.TestCase):
    # Newer iasWorld builds vary the results-table column order (owner/address
    # swapped, extra interleaved columns). Columns are mapped by their <th> header
    # labels, so no per-county column config is needed.

    def _config(self, **overrides: object) -> IasWorldSiteConfig:
        base = dict(
            source_id="us-oh-montgomery-auditor",
            county="Montgomery County",
            state="OH",
            name="Montgomery County, Ohio Auditor",
            base_url="https://www.mcrealestate.org/",
            district_code="000",
            numeric_parcel_ids=False,
        )
        base.update(overrides)
        return IasWorldSiteConfig(**base)

    def test_header_detection_maps_swapped_owner_address(self) -> None:
        # Montgomery build: headers Parcel ID / Owner / Parcel Location.
        html = (
            "<table>"
            "<tr><th>Parcel ID</th><th>Owner</th><th>Parcel Location</th></tr>"
            "<tr class='SearchResults'>"
            "<td>A01 00000 0001</td>"
            "<td>DOE JANE A</td>"
            "<td>100 EXAMPLE AVE</td>"
            "</tr></table>"
        )
        rows = IasWorldAuditorClient(self._config())._parse_search_results(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].parcel_id, "A01 00000 0001")
        self.assertEqual(rows[0].owner, "DOE JANE A")
        self.assertEqual(rows[0].address, "100 EXAMPLE AVE")

    def test_header_detection_skips_interleaved_and_checkbox_columns(self) -> None:
        # Summit build: All / Parcel / LUC / Route / Address / Owner / TaxYr, with a
        # leading empty select-checkbox cell and a stray "Selection Manager" header.
        html = (
            "<table>"
            "<tr><th>All</th><th>Parcel</th><th>LUC</th><th>Route</th>"
            "<th>Address</th><th>Owner</th><th>TaxYr</th></tr>"
            "<tr><th>Selection Manager</th></tr>"
            "<tr class='SearchResults'>"
            "<td></td><td>0100000</td><td>510</td><td>000000000000000</td>"
            "<td>100 EXAMPLE ST NW</td><td>DOE JOHN Q</td><td>2025</td>"
            "</tr></table>"
        )
        rows = IasWorldAuditorClient(self._config())._parse_search_results(html)
        self.assertEqual(rows[0].parcel_id, "0100000")
        self.assertEqual(rows[0].address, "100 EXAMPLE ST NW")
        self.assertEqual(rows[0].owner, "DOE JOHN Q")

    def test_no_header_falls_back_to_classic_positional(self) -> None:
        # A table without <th> headers keeps the classic parcel/address/owner order.
        html = (
            "<table><tr class='SearchResults'>"
            "<td>010-000123-00</td><td>100 EXAMPLE AVE</td><td>DOE JANE A</td>"
            "</tr></table>"
        )
        rows = IasWorldAuditorClient(FRANKLIN)._parse_search_results(html)
        self.assertEqual(rows[0].parcel_id, "010-000123-00")
        self.assertEqual(rows[0].address, "100 EXAMPLE AVE")
        self.assertEqual(rows[0].owner, "DOE JANE A")

    def test_preserve_parcel_whitespace_keeps_internal_spaces(self) -> None:
        from titlemcp_platform_iasworld.client import _compact_parcel_id

        # Default strips whitespace; the knob preserves the spaces the form needs.
        self.assertEqual(
            _compact_parcel_id("A01 00000 0001", numeric_only=False), "A01000000001"
        )
        self.assertEqual(
            _compact_parcel_id("A01 00000 0001", numeric_only=False, preserve_whitespace=True),
            "A01 00000 0001",
        )

    def test_parcel_search_submits_spaced_parcel_when_preserved(self) -> None:
        from titlemcp_platform_iasworld.client import _parcel_attempts
        from titlemcp_platform_iasworld.models import IasWorldAuditorSearchQuery

        query = IasWorldAuditorSearchQuery(
            mode=AuditorSearchMode.PARCEL_ID, parcel_id="A01 00000 0001"
        )
        attempts = _parcel_attempts(query, numeric_parcel_ids=False, preserve_whitespace=True)
        self.assertEqual(attempts[0][0]["inpParid"], "A01 00000 0001")


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


# Lake County serves a unified iasWorld "realprop" search whose form renames two
# POST fields. These tests pin both halves of that knob: every mode routes to the
# realprop URL, and the address-number / owner field names are remapped — while
# the classic counties (no overrides) keep posting inpNumber / inpOwner.
LAKE = IasWorldSiteConfig(
    source_id="us-oh-lake-auditor",
    county="Lake County",
    state="OH",
    name="Lake County, Ohio Auditor Property Search",
    base_url="https://auditor.lakecountyohio.gov/",
    district_code="000",
    numeric_parcel_ids=False,
    mode_map={
        AuditorSearchMode.ADDRESS: "realprop",
        AuditorSearchMode.OWNER: "realprop",
        AuditorSearchMode.PARCEL_ID: "realprop",
    },
    form_field_overrides={"inpNumber": "inpNo", "inpOwner": "inpOwner1"},
)


class IasWorldFormFieldOverrideTests(unittest.TestCase):
    def test_realprop_mode_map_routes_every_mode(self) -> None:
        for mode in (
            AuditorSearchMode.ADDRESS,
            AuditorSearchMode.OWNER,
            AuditorSearchMode.PARCEL_ID,
        ):
            self.assertEqual(
                LAKE.search_url(mode),
                "https://auditor.lakecountyohio.gov/search/commonsearch.aspx?mode=realprop",
            )

    def test_overrides_rename_address_and_owner_fields(self) -> None:
        client = IasWorldAuditorClient(LAKE)

        renamed = client._apply_field_overrides(
            {"inpNumber": "100", "inpAdrdir": "N", "inpStreet": "EXAMPLE", "inpUnit": ""}
        )

        # Address number is remapped; street/direction/unit keep their names.
        self.assertEqual(
            renamed, {"inpNo": "100", "inpAdrdir": "N", "inpStreet": "EXAMPLE", "inpUnit": ""}
        )

        owner_fields = client._apply_field_overrides({"inpOwner": "DOE JANE A"})
        self.assertEqual(owner_fields, {"inpOwner1": "DOE JANE A"})

        # Parcel field is shared and never renamed.
        self.assertEqual(
            client._apply_field_overrides({"inpParid": "00A0000000002"}),
            {"inpParid": "00A0000000002"},
        )

    def test_classic_counties_keep_field_names(self) -> None:
        # Backward-compatibility guard: no overrides means the dict passes through.
        client = IasWorldAuditorClient(FRANKLIN)

        self.assertEqual(
            client._apply_field_overrides({"inpNumber": "100", "inpOwner": "DOE JANE A"}),
            {"inpNumber": "100", "inpOwner": "DOE JANE A"},
        )

    def test_submitted_post_body_uses_lake_field_names(self) -> None:
        # End-to-end through _submit_search with a fake opener that captures the
        # POST body, proving the remap reaches the wire for an owner search.
        opener = _CaptureOpener(LAKE_SEARCH_HTML)
        client = IasWorldAuditorClient(LAKE, opener=opener)

        client.search(
            IasWorldAuditorSearchQuery(
                mode=AuditorSearchMode.OWNER,
                owner_name="DOE JANE A",
                include_details=False,
            )
        )

        self.assertTrue(opener.post_bodies, "expected at least one POST")
        body = opener.post_bodies[0]
        self.assertIn("inpOwner1=", body)
        self.assertNotIn("inpOwner=", body)


LAKE_SEARCH_HTML = """
<table id="searchResults">
  <tr class="SearchResults"
      onclick="javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=1')">
    <td><input name="chkPin" value="000:00A0000000002:2026"></td>
    <td><div>00A0000000002</div></td>
    <td><div>100 EXAMPLE ST</div></td>
    <td><div>DOE JANE A</div></td>
    <td><div>EXAMPLE SUBDIVISION LOT 1</div></td>
  </tr>
</table>
"""


class _CaptureResponse:
    def __init__(self, body: str, url: str) -> None:
        self._body = body.encode("utf-8")
        self._url = url

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _CaptureResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _CaptureOpener:
    """Minimal opener stand-in that records POST bodies and serves fixed HTML."""

    def __init__(self, search_html: str) -> None:
        self._search_html = search_html
        self.post_bodies: list[str] = []

    def open(self, request: object, timeout: float | None = None) -> _CaptureResponse:
        data = getattr(request, "data", None)
        url = getattr(request, "full_url", "https://auditor.lakecountyohio.gov/")
        if data is None:
            # The initial GET of the search form.
            return _CaptureResponse("<form></form>", url)
        self.post_bodies.append(data.decode("utf-8"))
        return _CaptureResponse(self._search_html, url)


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

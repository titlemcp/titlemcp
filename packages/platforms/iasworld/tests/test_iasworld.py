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
    is_datalet_shaped,
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

BUTLER = IasWorldSiteConfig(
    source_id="us-oh-butler-auditor",
    county="Butler County",
    state="OH",
    name="Butler County, Ohio Auditor Property Search",
    base_url="https://propertysearch.bcohio.gov/",
    district_code="000",
    numeric_parcel_ids=False,
    detail_profile=DetailProfile.PUBLIC_ACCESS_DETAILED,
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
    detail_profile=DetailProfile.LAKE,
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

    def test_public_access_detailed_parses_renamed_sections(self) -> None:
        detail = IasWorldAuditorClient(BUTLER).parse_detail(BUTLER_DETAIL_HTML)

        self.assertEqual(detail.parcel_number, "A0100001000001")
        self.assertEqual(detail.jurisdiction, "000")
        # Owner and legal share one table; mailing is named for the tax bill.
        self.assertEqual(detail.owners, ["DOE JANE A"])
        self.assertEqual(detail.legal_description, ["EXAMPLE CITY SUBDIVISION LOT 1"])
        self.assertEqual(
            detail.owner_mailing_address,
            ["100 EXAMPLE DR", "ANYTOWN OH 45000 0000"],
        )
        self.assertEqual(detail.site_property_address, "100 EXAMPLE DR")
        self.assertEqual(detail.legal_acres, "1.0000")
        # Normalized into the same keys the other profiles use.
        self.assertEqual(detail.tax_status["Property Class"], "RESIDENTIAL")
        self.assertEqual(detail.tax_status["Tax District"], "A01")
        self.assertEqual(detail.tax_status["Zip Code"], "45000")
        # Tables the plain Public Access variant has no equivalent for.
        self.assertEqual(
            detail.appraised_value["rows"][0],
            {
                "": "Market (100%)",
                "Land": "$40,000",
                "Improvements": "$200,000",
                "Total": "$240,000",
            },
        )
        self.assertEqual(detail.taxable_value["rows"][0]["Total"], "$84,000")
        self.assertEqual(detail.most_recent_transfer["Transfer Date"], "05-SEP-2017")
        self.assertEqual(detail.most_recent_transfer["Transfer Price"], "$250,000")
        self.assertEqual(
            detail.annual_taxes["rows"][0],
            {"Tax Year": "2026", "Net Annual Tax": "3,000.00", "Total Paid": "3,013.00"},
        )

    def test_plain_public_access_would_miss_butler_sections(self) -> None:
        # The regression this variant exists for: Butler renames every table but
        # "Parcel", so the plain profile silently returns empty owner/legal/
        # mailing/tax fields rather than failing.
        plain = IasWorldSiteConfig(
            source_id="us-oh-butler-auditor",
            county="Butler County",
            state="OH",
            name="Butler County, Ohio Auditor Property Search",
            base_url="https://propertysearch.bcohio.gov/",
            district_code="000",
            numeric_parcel_ids=False,
            detail_profile=DetailProfile.PUBLIC_ACCESS,
        )

        detail = IasWorldAuditorClient(plain).parse_detail(BUTLER_DETAIL_HTML)

        self.assertEqual(detail.owners, [])
        self.assertEqual(detail.legal_description, [])
        self.assertEqual(detail.owner_mailing_address, [])
        self.assertEqual(detail.annual_taxes, {})
        # The "Parcel" table matches either way, which is why this looked partly right.
        self.assertEqual(detail.legal_acres, "1.0000")

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


# Butler's datalet. Table and label names mirror a live page; the values are
# placeholders, like every other fixture here. Same numbered labels as Clermont,
# but owner and legal share a table, mailing is named for the tax bill, and the
# page adds value, transfer and half-year tax tables.
BUTLER_DETAIL_HTML = """
<table id="Parcel">
  <tr><td>Parcel Id</td><td>A0100001000001</td></tr>
  <tr><td>Address</td><td>100 EXAMPLE DR</td></tr>
  <tr><td>Class</td><td>RESIDENTIAL</td></tr>
  <tr><td>Land Use Code**</td><td>510 R - SINGLE FAMILY DWELLING, PLATTED LOT</td></tr>
  <tr><td>Neighborhood</td><td>R0000001</td></tr>
  <tr><td>Total Acres</td><td>1.0000</td></tr>
  <tr><td>Taxing District</td><td>A01</td></tr>
  <tr><td>District Name</td><td>EXAMPLE TWP-EXAMPLE CSD</td></tr>
</table>
<table id="Owner and Legal">
  <tr><td>Owner 1</td><td>DOE JANE A</td></tr>
  <tr><td>Owner 2</td><td></td></tr>
  <tr><td>Legal 1</td><td>EXAMPLE CITY SUBDIVISION LOT 1</td></tr>
  <tr><td>Legal 2</td><td></td></tr>
</table>
<table id="Taxbill Mailing Address">
  <tr><td>Mailing Name 1</td><td>JANE A DOE</td></tr>
  <tr><td>Address 1</td><td>100 EXAMPLE DR</td></tr>
  <tr><td>Address 2</td><td></td></tr>
  <tr><td>Address 3</td><td>ANYTOWN OH 45000 0000</td></tr>
</table>
<table id="Current Value">
  <tr><td>Land (100%)</td><td>$40,000</td></tr>
  <tr><td>Building (100%)</td><td>$200,000</td></tr>
  <tr><td>Total Value (100%)</td><td>$240,000</td></tr>
  <tr><td>CAUV</td><td>$0</td></tr>
  <tr><td>Assessed Tax Year</td><td>2025</td></tr>
  <tr><td>Land (35%)</td><td>$14,000</td></tr>
  <tr><td>Building (35%)</td><td>$70,000</td></tr>
  <tr><td>Assessed Total (35%)</td><td>$84,000</td></tr>
</table>
<table id="Transfers">
  <tr><td>Date</td><td>Sale Amount</td></tr>
  <tr><td>05-SEP-2017</td><td>$250,000</td></tr>
  <tr><td>01-APR-1997</td><td>$120,000</td></tr>
</table>
<table id="Current Year Real Estate Taxes">
  <tr><td>TAX TYPE</td><td>Prior Year</td><td>First Half Tax</td><td>Second Half Tax</td><td>Total</td></tr>
  <tr><td>Real Estate</td><td>0.00</td><td>1,500.00</td><td>1,500.00</td><td>3,000.00</td></tr>
  <tr><td>Special Assessments</td><td>0.00</td><td>6.50</td><td>6.50</td><td>13.00</td></tr>
  <tr><td>Tot Payments</td><td>0.00</td><td>-1,506.50</td><td>-1,506.50</td><td>-3,013.00</td></tr>
</table>
<input type="hidden" id="hdPin" value="A0100001000001" />
<input type="hidden" id="hdTaxYear" value="2026" />
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


# Synthetic Lake markup (fake owner/parcel/address) structured like the live Lake
# datalet: section ids carry trailing anchor markup, empty fields are "-", labels
# are singular, and the value tables are prefixed and keyed by Year. Lake serves
# no DataletHeader table, which this fixture also reproduces.
LAKE_DETAIL_HTML = """
<table id="Parcel">
  <tr><td>Class</td><td>R - RESIDENTIAL</td></tr>
  <tr><td>Land Use Code **</td><td>510 - R - SINGLE FAMILY (Land Use Codes Descriptions)</td></tr>
  <tr><td>Tax Roll</td><td>RP_OH</td></tr>
  <tr><td>Neighborhood</td><td>01R04000 -</td></tr>
  <tr><td>Municipality</td><td>01 - EXAMPLE TOWNSHIP</td></tr>
  <tr><td>**Land Use Code(LUC) is for valuation purposes only.</td></tr>
</table>
<table id="Owner Name and Mailing Address<a href=&quot;https://example.test/smartfile&quot;><small>Change address</small></a>">
  <tr><td>Owner Name</td><td>DOE JANE A</td></tr>
  <tr><td>Owner Mailing Address</td><td>100 EXAMPLE ST</td></tr>
  <tr><td>City, State, Zip</td><td>ANYTOWN OH 44000</td></tr>
</table>
<table id="Legal Description Information">
  <tr><td>Multiple Parcel:</td><td>-</td></tr>
  <tr><td>Legal Description</td><td>EXAMPLE SUBDIVISION LOT 1</td></tr>
  <tr><td>AG Status</td><td>-</td></tr>
  <tr><td>Subdivison/Condo Name</td><td>-</td></tr>
</table>
<table id="Appraised (Market - 100%) Value">
  <tr><td>Year</td><td>Parcel ID</td><td>Appraised Land</td><td>Appraised Building</td><td>Appraised Total</td><td>CAUV</td></tr>
  <tr><td>2025</td><td>00A0000000002</td><td>$30,000</td><td>$120,000</td><td>$150,000</td><td>$0</td></tr>
  <tr><td>Total:</td><td></td><td>$30,000</td><td>$120,000</td><td>$150,000</td><td>$0</td></tr>
</table>
<table id="Assessed Value (35%)">
  <tr><td>Year</td><td>Parcel ID</td><td>Assessed Land</td><td>Assessed Building</td><td>Assessed Total</td><td>CAUV</td></tr>
  <tr><td>2025</td><td>00A0000000002</td><td>$10,500</td><td>$42,000</td><td>$52,500</td><td>$0</td></tr>
  <tr><td>Total:</td><td></td><td>$10,500</td><td>$42,000</td><td>$52,500</td><td>$0</td></tr>
</table>
<table id="Taxes Due">
  <tr><td>Tax Roll</td><td>Delq Taxes</td><td>1ST Half Taxes</td><td>2ND Half Taxes</td><td>Total</td></tr>
  <tr><td>RP_OH</td><td>$0.00</td><td>$1,250.00</td><td>$1,250.00</td><td>$2,500.00</td></tr>
</table>
<input type="hidden" id="hdPin" value="00A0000000002" />
<input type="hidden" id="hdTaxYear" value="2026" />
<input type="hidden" id="hdJur" value="000" />
"""


class LakeDetailProfileTests(unittest.TestCase):
    """Lake is a third datalet layout; the profile normalizes it to the shared shape."""

    def setUp(self) -> None:
        self.detail = IasWorldAuditorClient(LAKE).parse_detail(LAKE_DETAIL_HTML)

    def test_identifiers_come_from_hidden_inputs_without_a_header_table(self) -> None:
        # Lake serves no DataletHeader, so the hidden-input fallback is the only
        # source of the parcel/jur/year triple.
        self.assertEqual(self.detail.parcel_number, "00A0000000002")
        self.assertEqual(self.detail.jurisdiction, "000")
        self.assertEqual(self.detail.tax_year, "2026")
        self.assertEqual(self.detail.parcel_token, "000:00A0000000002:2026")

    def test_singular_labels_populate_owner_and_legal_fields(self) -> None:
        self.assertEqual(self.detail.owners, ["DOE JANE A"])
        self.assertEqual(
            self.detail.owner_mailing_address, ["100 EXAMPLE ST", "ANYTOWN OH 44000"]
        )
        self.assertEqual(self.detail.legal_description, ["EXAMPLE SUBDIVISION LOT 1"])

    def test_section_ids_with_trailing_anchor_markup_are_matched(self) -> None:
        # The owner section id embeds an <a> tag; normalization must strip it.
        self.assertIn("Owner Name and Mailing Address", self.detail.sections)

    def test_tax_status_normalizes_into_the_shared_keys(self) -> None:
        self.assertEqual(
            self.detail.tax_status,
            {
                "Property Class": "R - RESIDENTIAL",
                "Land Use": "510 - R - SINGLE FAMILY",
                # Trailing "code -" separator dropped when the name is empty.
                "Appraisal Neighborhood": "01R04000",
                "City/Village": "01 - EXAMPLE TOWNSHIP",
                "Zip Code": "44000",
            },
        )

    def test_placeholder_dashes_do_not_reach_extracted_fields(self) -> None:
        # Lake writes "-" for empty fields. Those must not surface as values...
        extracted = [
            *self.detail.legal_description,
            *self.detail.owners,
            *self.detail.owner_mailing_address,
            *self.detail.tax_status.values(),
        ]
        self.assertNotIn("-", [str(value).strip() for value in extracted])

        # ...but the raw section payload still preserves them as source evidence.
        legal = self.detail.sections["Legal Description Information"]["fields"]
        self.assertEqual(legal["AG Status"], "-")

    def test_prefixed_value_tables_reshape_to_land_improvements_total(self) -> None:
        self.assertEqual(
            self.detail.appraised_value["rows"],
            [
                {
                    "Category": "2025",
                    "Land": "$30,000",
                    "Improvements": "$120,000",
                    "Total": "$150,000",
                }
            ],
        )
        self.assertEqual(self.detail.taxable_value["rows"][0]["Total"], "$52,500")

    def test_taxes_due_rollup_becomes_the_annual_tax_row(self) -> None:
        self.assertEqual(
            self.detail.annual_taxes["rows"], [{"Tax Year": "2026", "Net Annual Tax": "$2,500.00"}]
        )

    def test_site_address_and_transfer_are_absent_not_guessed(self) -> None:
        # The detail page carries neither; the mailing address is NOT a stand-in.
        self.assertIsNone(self.detail.site_property_address)
        self.assertEqual(self.detail.most_recent_transfer, {})

    def test_other_profiles_are_unaffected_by_lake_handling(self) -> None:
        classic = IasWorldAuditorClient(FRANKLIN).parse_detail(DETAIL_HTML)
        public_access = IasWorldAuditorClient(CLERMONT).parse_detail(CLERMONT_DETAIL_HTML)

        self.assertTrue(classic.owners)
        self.assertEqual(public_access.site_property_address, "100 EXAMPLE DR")


# A county site under maintenance, behind a bot block, or erroring serves these
# with HTTP 200, so nothing raises and they parse into a hollow detail.
MAINTENANCE_HTML = """
<html><body><h1>Site Under Maintenance</h1>
<p>The property search is temporarily unavailable. Please try again later.</p>
</body></html>
"""

BOT_BLOCK_HTML = """
<html><body><h1>Access Denied</h1>
<p>Your request has been blocked.</p></body></html>
"""


class UnreadableDetailTests(unittest.TestCase):
    """A 200 that is not a datalet must not read as a parcel with empty fields."""

    def test_maintenance_page_is_not_datalet_shaped(self) -> None:
        for label, html in (
            ("maintenance", MAINTENANCE_HTML),
            ("bot block", BOT_BLOCK_HTML),
        ):
            with self.subTest(page=label):
                detail = IasWorldAuditorClient(CLERMONT).parse_detail(html)

                # It parses without raising, which is the whole problem.
                self.assertEqual(detail.raw_section_rows, {})
                self.assertIsNone(detail.parcel_number)
                self.assertFalse(is_datalet_shaped(detail))

    def test_real_datalet_is_datalet_shaped(self) -> None:
        detail = IasWorldAuditorClient(CLERMONT).parse_detail(CLERMONT_DETAIL_HTML)

        self.assertTrue(is_datalet_shaped(detail))
        self.assertEqual(detail.warnings, [])

    def test_unreadable_detail_is_dropped_and_warned(self) -> None:
        client = _StubbedDetailClient(CLERMONT, detail_html=MAINTENANCE_HTML)

        response = client.search(
            IasWorldAuditorSearchQuery(
                mode=AuditorSearchMode.PARCEL_ID,
                parcel_id="100200C003D",
                include_details=True,
            )
        )

        # The hit still stands; only the unreadable detail is withheld.
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.details, [])
        self.assertEqual(len(response.warnings), 1)
        self.assertIn("no readable datalet", response.warnings[0])
        self.assertIn("maintenance or bot protection", response.warnings[0])

    def test_readable_detail_is_kept_without_warnings(self) -> None:
        client = _StubbedDetailClient(CLERMONT, detail_html=CLERMONT_DETAIL_HTML)

        response = client.search(
            IasWorldAuditorSearchQuery(
                mode=AuditorSearchMode.PARCEL_ID,
                parcel_id="100200C003D",
                include_details=True,
            )
        )

        self.assertEqual(len(response.details), 1)
        self.assertEqual(response.warnings, [])


class ProfileMismatchWarningTests(unittest.TestCase):
    """A renamed-tables county parses cleanly but populates nothing."""

    def test_wrong_profile_warns_instead_of_reporting_empty_fields(self) -> None:
        # Butler's datalet under the plain profile: every section is present,
        # none of them match, so the record would otherwise look simply blank.
        plain = IasWorldSiteConfig(
            source_id="us-oh-butler-auditor",
            county="Butler County",
            state="OH",
            name="Butler County, Ohio Auditor Property Search",
            base_url="https://propertysearch.bcohio.gov/",
            district_code="000",
            numeric_parcel_ids=False,
            detail_profile=DetailProfile.PUBLIC_ACCESS,
        )

        detail = IasWorldAuditorClient(plain).parse_detail(
            BUTLER_DETAIL_HTML, source_url="https://example.test/butler"
        )

        self.assertEqual(detail.owners, [])
        self.assertEqual(len(detail.warnings), 1)
        warning = detail.warnings[0]
        self.assertIn("detail_profile=public_access matched none", warning)
        self.assertIn("https://example.test/butler", warning)
        # The warning names what the page actually served, so the fix is obvious.
        self.assertIn("Owner and Legal", warning)
        self.assertIn("Taxbill Mailing Address", warning)

    def test_correct_profile_does_not_warn(self) -> None:
        detail = IasWorldAuditorClient(BUTLER).parse_detail(BUTLER_DETAIL_HTML)

        self.assertEqual(detail.owners, ["DOE JANE A"])
        self.assertEqual(detail.warnings, [])

    def test_mismatch_warning_reaches_the_search_response(self) -> None:
        plain = IasWorldSiteConfig(
            source_id="us-oh-butler-auditor",
            county="Butler County",
            state="OH",
            name="Butler County, Ohio Auditor Property Search",
            base_url="https://propertysearch.bcohio.gov/",
            district_code="000",
            numeric_parcel_ids=False,
            detail_profile=DetailProfile.PUBLIC_ACCESS,
        )
        client = _StubbedDetailClient(plain, detail_html=BUTLER_DETAIL_HTML)

        response = client.search(
            IasWorldAuditorSearchQuery(
                mode=AuditorSearchMode.PARCEL_ID,
                parcel_id="A0100001000001",
                include_details=True,
            )
        )

        # The record is still returned, but no longer silently blank.
        self.assertEqual(len(response.details), 1)
        self.assertEqual(len(response.warnings), 1)
        self.assertIn("matched none of the datalet sections", response.warnings[0])


# Montgomery's datalet. Labelled rather than numbered: the owner table is a
# single column under a "Name" header, multi-line values continue on rows whose
# label cell is blank, and the sales table is oldest first. Values are synthetic.
MONTGOMERY_DETAIL_HTML = """
<table id="Owner">
  <tr><td>Name</td></tr>
  <tr><td>DOE JANE A AND JOHN Q TRS</td></tr>
</table>
<table id="Mailing">
  <tr><td>Name</td><td>JANE A DOE AND</td></tr>
  <tr><td></td><td>JOHN Q DOE TRS</td></tr>
  <tr><td>Mailing Address</td><td>100 EXAMPLE DR</td></tr>
  <tr><td>City, State, Zip</td><td>ANYTOWN, OH 45000</td></tr>
</table>
<table id="Legal">
  <tr><td>Legal Description</td><td>5-5-24</td></tr>
  <tr><td></td><td>1-9-13</td></tr>
  <tr><td>Land Use Description</td><td>R - SINGLE FAMILY DWELLING</td></tr>
  <tr><td>Acres</td><td>1.234</td></tr>
  <tr><td>Deed</td><td></td></tr>
  <tr><td>Tax District Name</td><td>EXAMPLE TWP-EXAMPLE CSD</td></tr>
</table>
<table id="Sales">
  <tr><td>Date</td><td>Sale Price</td><td>Deed Reference</td><td>Seller</td><td>Buyer</td></tr>
  <tr><td>04-OCT-05</td><td>$120,000</td><td>200500101830</td><td>ROE R</td><td>DOE JANE A</td></tr>
  <tr><td>28-FEB-18</td><td>$250,000</td><td>201800011199</td><td>DOE JANE A</td><td>DOE JANE A AND JOHN Q TRS</td></tr>
</table>
<table id="Tax Summary">
  <tr><td>Year</td><td>Prior Year</td><td>Prior Year Payments</td><td>1st Half</td><td>1st Half Payments</td><td>2nd Half</td><td>2nd Half Payments</td><td>Total Currently Due</td></tr>
  <tr><td>2025</td><td>$0.00</td><td>$0.00</td><td>$1,000.00</td><td>-$1,000.00</td><td>$1,500.00</td><td>-$1,500.00</td><td>$0.00</td></tr>
</table>
<input type="hidden" id="hdPin" value="A01000000001" />
<input type="hidden" id="hdTaxYear" value="2025" />
<input type="hidden" id="hdJur" value="000" />
"""


# Lucas's datalet: a "Summary - " tabbed page. It carries no owner, mailing
# address or legal description at all, and its value table is transposed.
LUCAS_DETAIL_HTML = """
<table id="Summary - General">
  <tr><td>Tax District</td><td>EXAMPLE CITY - EXAMPLE CSD</td></tr>
  <tr><td>Class</td><td>RESIDENTIAL</td></tr>
  <tr><td>Land Use</td><td>520 : R - TWO FAMILY DWELLING, PLATTED LOT</td></tr>
</table>
<table id="Summary - Most Recent Sale">
  <tr><td>Prior Owner</td><td>ROE RICHARD L</td></tr>
  <tr><td>Sale Amount</td><td>$100</td></tr>
  <tr><td>Deed</td><td>25103809</td></tr>
  <tr><td>Sales Date</td><td>10-JUL-2025</td></tr>
</table>
<table id="Summary - Values">
  <tr><td></td><td>35% Values</td><td>100% Values</td></tr>
  <tr><td>Land</td><td>4,830</td><td>13,800</td></tr>
  <tr><td>Building</td><td>19,110</td><td>54,600</td></tr>
  <tr><td>Total</td><td>23,940</td><td>68,400</td></tr>
</table>
<input type="hidden" id="hdPin" value="0100437" />
<input type="hidden" id="hdTaxYear" value="2026" />
<input type="hidden" id="hdJur" value="048" />
"""

MONTGOMERY_KEYED = IasWorldSiteConfig(
    source_id="us-oh-montgomery-auditor",
    county="Montgomery County",
    state="OH",
    name="Montgomery County, Ohio Auditor Property Search",
    base_url="https://www.mcrealestate.org/",
    district_code="000",
    numeric_parcel_ids=False,
    detail_profile=DetailProfile.PUBLIC_ACCESS_KEYED,
)

LUCAS_SUMMARY = IasWorldSiteConfig(
    source_id="us-oh-lucas-auditor",
    county="Lucas County",
    state="OH",
    name="Lucas County, Ohio Auditor Property Search (AREIS)",
    base_url="https://icare.co.lucas.oh.us/lucascare/",
    district_code="048",
    detail_profile=DetailProfile.SUMMARY_SECTIONS,
)


class KeyedLabelLayoutTests(unittest.TestCase):
    """Montgomery: labelled rows, a single-column owner table, continuations."""

    def setUp(self) -> None:
        self.detail = IasWorldAuditorClient(MONTGOMERY_KEYED).parse_detail(
            MONTGOMERY_DETAIL_HTML
        )

    def test_single_column_owner_table_is_read(self) -> None:
        self.assertEqual(self.detail.owners, ["DOE JANE A AND JOHN Q TRS"])

    def test_blank_labels_continue_the_line_above(self) -> None:
        # The legal description runs across two rows, the second unlabelled.
        self.assertEqual(self.detail.legal_description, ["5-5-24", "1-9-13"])
        # A continuation must not leak from a label this layout does not want:
        # "Name" continues onto a second row, but mailing takes only the address.
        self.assertEqual(
            self.detail.owner_mailing_address,
            ["100 EXAMPLE DR", "ANYTOWN, OH 45000"],
        )

    def test_labelled_parcel_fields_normalize(self) -> None:
        self.assertEqual(self.detail.legal_acres, "1.234")
        self.assertEqual(self.detail.tax_status["Land Use"], "R - SINGLE FAMILY DWELLING")
        self.assertEqual(self.detail.tax_status["Tax District"], "EXAMPLE TWP-EXAMPLE CSD")
        self.assertEqual(self.detail.tax_status["Zip Code"], "45000")

    def test_oldest_first_sales_table_takes_the_last_row(self) -> None:
        self.assertEqual(self.detail.most_recent_transfer["Transfer Date"], "28-FEB-18")
        self.assertEqual(self.detail.most_recent_transfer["Transfer Price"], "$250,000")

    def test_half_year_columns_are_summed_into_the_annual_charge(self) -> None:
        self.assertEqual(
            self.detail.annual_taxes["rows"][0],
            {"Tax Year": "2025", "Net Annual Tax": "2,500.00", "Total Paid": "2,500.00"},
        )

    def test_no_mismatch_warning(self) -> None:
        self.assertEqual(self.detail.warnings, [])


class SummarySectionsLayoutTests(unittest.TestCase):
    """Lucas: a tab that genuinely carries no owner, mailing or legal."""

    def setUp(self) -> None:
        self.detail = IasWorldAuditorClient(LUCAS_SUMMARY).parse_detail(LUCAS_DETAIL_HTML)

    def test_transposed_value_table_is_reshaped(self) -> None:
        self.assertEqual(
            self.detail.appraised_value["rows"][0],
            {
                "": "Market (100%)",
                "Land": "13,800",
                "Improvements": "54,600",
                "Total": "68,400",
            },
        )
        self.assertEqual(self.detail.taxable_value["rows"][0]["Total"], "23,940")

    def test_keyed_sale_section_becomes_the_transfer(self) -> None:
        self.assertEqual(self.detail.most_recent_transfer["Transfer Date"], "10-JUL-2025")
        self.assertEqual(self.detail.most_recent_transfer["Transfer Price"], "$100")

    def test_tax_status_normalizes(self) -> None:
        self.assertEqual(self.detail.tax_status["Property Class"], "RESIDENTIAL")
        self.assertEqual(self.detail.tax_status["Tax District"], "EXAMPLE CITY - EXAMPLE CSD")

    def test_absent_fields_do_not_warn(self) -> None:
        # The regression this guards: owner/mailing/legal are empty because the
        # page has none, not because the profile is wrong, so no warning fires.
        self.assertEqual(self.detail.owners, [])
        self.assertEqual(self.detail.owner_mailing_address, [])
        self.assertEqual(self.detail.legal_description, [])
        self.assertEqual(self.detail.warnings, [])

    def test_a_genuinely_wrong_profile_still_warns(self) -> None:
        # Same page under a profile that does expect an owner table.
        wrong = LUCAS_SUMMARY.model_copy(
            update={"detail_profile": DetailProfile.PUBLIC_ACCESS}
        )

        detail = IasWorldAuditorClient(wrong).parse_detail(LUCAS_DETAIL_HTML)

        self.assertEqual(len(detail.warnings), 1)
        self.assertIn("matched none of the datalet sections", detail.warnings[0])


class _StubbedDetailClient(IasWorldAuditorClient):
    """Drives the real search/detail flow with canned HTTP responses."""

    def __init__(self, config: IasWorldSiteConfig, *, detail_html: str) -> None:
        super().__init__(config)
        self._detail_html = detail_html

    def _submit_search(self, query, fields, sort_by):  # type: ignore[no-untyped-def]
        return CLERMONT_SEARCH_HTML, "https://example.test/search", None

    def _get(self, url: str):  # type: ignore[no-untyped-def]
        return self._detail_html, url


if __name__ == "__main__":
    unittest.main()

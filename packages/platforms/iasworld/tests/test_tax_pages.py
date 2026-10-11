from __future__ import annotations

# ruff: noqa: E501
import asyncio
import unittest
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.tax import PropertyTaxQuery, TaxStatus, tax_status
from title_mcp.sources import SourceResultStatus
from titlemcp_platform_iasworld import (
    AuditorSearchMode,
    IasWorldAuditorClient,
    IasWorldSiteConfig,
    TaxDueDate,
    TaxPage,
    build_auditor_source_connector,
    same_parcel,
)
from titlemcp_platform_iasworld.tax import TAX_TABS, tax_parcel_from_pages

BASE = "https://tax.sample.example/pt/"
SAMPLE = Jurisdiction(country="US", state="XX", county="Sample County")
TODAY = date(2026, 10, 11)


def _config(tax_page: TaxPage, **kwargs) -> IasWorldSiteConfig:
    return IasWorldSiteConfig(
        source_id="xx-sample-tax",
        county="Sample County",
        state="XX",
        name="Sample County Tax Search",
        base_url=BASE,
        district_code="900",
        owner="Sample County Treasurer",
        tax_page=tax_page,
        **kwargs,
    )


SUMMARY = _config(
    TaxPage.CURRENT_YEAR_SUMMARY,
    numeric_parcel_ids=False,
    tax_due_dates=[
        TaxDueDate(label="1st half", month=7, day=28),
        TaxDueDate(label="2nd half", month=12, day=5),
    ],
)
BILLED = _config(
    TaxPage.BILLED_AND_PAYMENTS,
    tax_due_dates=[
        TaxDueDate(label="1st installment", month=6, day=1, years_after_tax_year=1),
        TaxDueDate(label="2nd installment", month=9, day=1, years_after_tax_year=1),
    ],
)
BALANCE = _config(
    TaxPage.BALANCE_DUE,
    mode_map={mode: "realprop" for mode in AuditorSearchMode},
    form_field_overrides={"inpNumber": "inpNo", "inpOwner": "inpOwner1"},
    tax_due_dates=[
        TaxDueDate(label="1st half", month=11, day=10),
        TaxDueDate(label="2nd half", month=4, day=10, years_after_tax_year=1),
    ],
)
RECEIVABLE = _config(
    TaxPage.COUNTY_RECEIVABLE,
    tax_due_months_after_billing=4,
    tax_notes=["The county's site shows county tax only."],
)

DISCLAIMER_PAGE = """
<form name="Form1" method="post" action="./Disclaimer.aspx?FromUrl=..%2fsearch%2fcommonsearch.aspx%3fmode%3dparid">
  <input type="hidden" name="__VIEWSTATE" value="abc" />
  <input name="hdURL" type="hidden" value="../search/commonsearch.aspx?mode=parid" />
  <button type="submit" name="btDisagree">Disagree</button>
  <button type="submit" name="btAgree">Agree</button>
</form>
"""

SEARCH_FORM = """
<form><input type="hidden" name="__VIEWSTATE" value="abc" /><input name="inpParid" /></form>
<script>var siteYear = "2025";</script>
"""

NO_DATA_TAB = """
<p>-- No Data --</p>
<table id="Table1"><tr><td>Reports</td></tr></table>
"""


def _header(pin: str, *, jur: str = "900", tax_year: str = "2025") -> str:
    return f"""
<table><tr class="DataletHeaderTop"><td class="DataletHeaderTop">PARCEL: {pin}</td></tr></table>
<input type="hidden" id="hdPin" value="{pin.replace(" ", "&#32;")}" />
<input type="hidden" id="hdJur" value="{jur}" />
<input type="hidden" id="hdTaxYear" value="{tax_year}" />
"""


SUMMARY_PARCEL_PAGE = (
    _header("9999 01  0001A", tax_year="2027")
    + """
<table id="Parcel"><tr><td>Property Location</td><td>100 EXAMPLE AVE</td></tr></table>
<table id="Last Refresh"><tr><td>Date</td></tr><tr><td>Data last refreshed: October   02, 2026</td></tr></table>
"""
)

SUMMARY_TAB = (
    _header("9999 01  0001A", tax_year="2027")
    + """
<table id="Summary of Current Year Taxes">
  <tr><td>Year</td><td></td><td>General Fund Net Taxes</td><td>Special Tax District</td><td>Service Charges</td><td>Interest</td><td>Penalty</td><td>Other Charges</td><td>Amount Paid</td><td>Balance Due</td></tr>
  <tr><td>2026</td><td>1ST HALF DUE</td><td>$2,000.00</td><td>$150.00</td><td>$.00</td><td>$12.50</td><td>$215.00</td><td>$.00</td><td>-$2,377.50</td><td>$.00</td></tr>
  <tr><td>2026</td><td>2ND HALF DUE</td><td>$2,000.00</td><td>$150.00</td><td>$.00</td><td>$.00</td><td>$.00</td><td>$.00</td><td>$.00</td><td>$2,150.00</td></tr>
  <tr><td>Total:</td><td></td><td>$4,000.00</td><td>$300.00</td><td>$.00</td><td>$12.50</td><td>$215.00</td><td>$.00</td><td>-$2,377.50</td><td>$2,150.00</td></tr>
</table>
<table id="Prepays and Refunds">
  <tr><td>Prepays</td><td>$.00</td></tr>
  <tr><td>Pending Refunds</td><td>$25.00</td></tr>
  <tr><td>GRAND TOTAL</td><td>$2,150.00</td></tr>
</table>
"""
)

BILLED_PAGE = (
    _header("9990001234")
    + """
<table id="Taxes Billed">
  <tr><td>Tax Year</td><td>Tax</td></tr>
  <tr><td>2025</td><td>$6,000.00</td></tr>
  <tr><td>Total:</td><td>$6,000.00</td></tr>
</table>
<table id="Table1"><tr><td>Reports</td></tr></table>
"""
)

PAYMENTS_TAB = (
    _header("9990001234")
    + """
<table id="Payment Details">
  <tr><td>Year</td><td>Tax</td><td>Interest</td><td>Penalty</td><td>Cost</td><td>Total</td><td>Date Paid</td><td>Pay Type</td></tr>
  <tr><td>2025</td><td>3,000.00</td><td>.00</td><td>.00</td><td>.00</td><td>$3,000.00</td><td>05/28/2026</td><td>1ST</td></tr>
  <tr><td>2024</td><td>2,900.00</td><td>.00</td><td>.00</td><td>.00</td><td>$2,900.00</td><td>08/28/2025</td><td>STD</td></tr>
  <tr><td>2024</td><td>2,900.00</td><td>.00</td><td>.00</td><td>.00</td><td>$2,900.00</td><td>05/28/2025</td><td>1ST</td></tr>
</table>
"""
)

SOLD_TAB = (
    _header("9990001234")
    + """
<table id="Sold Taxes">
  <tr><td>Tax Year</td><td>Sale Date</td><td>Amount to Redeem</td></tr>
  <tr><td>2023</td><td>11/14/2024</td><td>$3,410.00</td></tr>
</table>
"""
)

FORFEITED_TAB = (
    _header("9990001234")
    + """
<table id="Tax Status"><tr><td>Status</td><td>FORFEITED</td></tr></table>
"""
)

BALANCE_RESULTS = """
<table id="searchResults">
  <tr class="SearchResults"
      onclick="javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=1')">
    <td><div>999000000000000001</div></td>
    <td><div>100 EXAMPLE AVE NE</div></td>
    <td><div>DOE JANE A</div></td>
  </tr>
</table>
"""

COPYRIGHT_ONLY = """
<table id="Table2" class="AkandaCopyright"><tr><td>Data Copyright Sample County</td></tr></table>
"""

BALANCE_TAB = (
    _header("999000000000000001")
    + """
<table id="Payment History">
  <tr><td>Prior YR:</td><td>Tax:</td><td>Int:</td><td>Pen:</td><td>Fees:</td><td>Paid:</td><td>Due:</td></tr>
  <tr><td>2025</td><td>2,000.00</td><td>40.00</td><td>100.00</td><td>.00</td><td>-1,000.00</td><td>1,140.00</td></tr>
  <tr><td>2024</td><td>1,900.00</td><td>.00</td><td>.00</td><td>.00</td><td>-1,900.00</td><td>.00</td></tr>
</table>
<table id="Current Amount Due">
  <tr><td></td><td>Tax:</td><td>Int:</td><td>Pen:</td><td>Fees:</td><td>Paid:</td><td>Due:</td></tr>
  <tr><td>1st half due</td><td>1,000.00</td><td>.00</td><td>.00</td><td>.00</td><td>-1,000.00</td><td>.00</td></tr>
  <tr><td>2nd half due</td><td>1,000.00</td><td>40.00</td><td>100.00</td><td>.00</td><td>.00</td><td>1,140.00</td></tr>
  <tr><td>Total Due</td><td>2,000.00</td><td>40.00</td><td>100.00</td><td>.00</td><td>-1,000.00</td><td>1,140.00</td></tr>
</table>
<table id="Pending Payment Balance">
  <tr><td>Monthly Payment Program Balance:</td><td>.00</td></tr>
  <tr><td>Total Due:</td><td>1,140.00</td></tr>
  <tr><td>Total due valid until</td><td>31-OCT-2026</td></tr>
</table>
"""
)

RECEIVABLE_PAGE = (
    _header("99000001200", tax_year="2026")
    + """
<table id="County Tax Receivable">
  <tr><td>Tax Year</td><td>Billing Year</td><td>Billing Period</td><td>Billing Date</td><td>Face Amount Due</td><td>Discount Posted</td><td>Penalty Posted</td><td>Fees Posted</td><td>Payment Posted</td><td>Balance</td><td>Pay Date</td><td>Type</td></tr>
  <tr><td>2026</td><td>2026</td><td>Original</td><td>02/01/2026</td><td>1,200.00</td><td></td><td>120.00</td><td></td><td></td><td>1,320.00</td><td></td><td></td></tr>
  <tr><td>2025</td><td>2025</td><td>Original</td><td>02/01/2025</td><td>1,150.00</td><td>-23.00</td><td></td><td></td><td>-1,127.00</td><td>0.00</td><td>03/20/2025</td><td>Discount</td></tr>
</table>
<table id="Delinquent Tax"><tr><td>No Outstanding Delinquent Amounts Found</td></tr></table>
<p>Copyright Sample County | Last Updated:&nbsp;</span><span id="lbLastUpdate">October   03, 2026</span></p>
"""
)


class _Response:
    def __init__(self, body: str, url: str) -> None:
        self._body, self._url = body.encode("utf-8"), url

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Site:
    """Serves invented pages the way an iasWorld site does, and records each request.

    ``found`` answers a search: a parcel page sends the visitor straight to the
    datalet, a results table lists hits. ``tabs`` serves Datalet.aspx by mode.
    """

    def __init__(self, *, found: str, tabs: dict[str, str], disclaimer: bool = False) -> None:
        self.found = found
        self.tabs = tabs
        self.disclaimer = disclaimer
        self.agreed = not disclaimer
        self.requests: list[tuple[str, str | None]] = []

    def open(self, request, timeout: float | None = None) -> _Response:
        url = request.full_url
        data = request.data.decode("utf-8") if request.data else None
        self.requests.append((url, data))
        if "Disclaimer.aspx" in url and data is not None:
            self.agreed = "btAgree" in data
            return _Response(SEARCH_FORM, f"{BASE}search/commonsearch.aspx?mode=parid")
        if not self.agreed:
            return _Response(
                DISCLAIMER_PAGE,
                f"{BASE}Search/Disclaimer.aspx?FromUrl=../search/commonsearch.aspx?mode=parid",
            )
        if "commonsearch.aspx" in url:
            if data is None:
                return _Response(SEARCH_FORM, url)
            if "SearchResults" in self.found:
                return _Response(self.found, url)
            return _Response(self.found, f"{BASE}Datalets/Datalet.aspx?sIndex=0&idx=1")
        mode = parse_qs(urlparse(url).query).get("mode", [""])[0]
        return _Response(self.tabs.get(mode, NO_DATA_TAB), url)


def _pages(config: IasWorldSiteConfig, site: _Site, parcel_id: str):
    client = IasWorldAuditorClient(config, opener=site)
    return client.tax_pages(parcel_id, TAX_TABS[config.tax_page])


class CurrentYearSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = _Site(found=SUMMARY_PARCEL_PAGE, tabs={"tax_details": SUMMARY_TAB})
        pages = _pages(SUMMARY, self.site, "9999-01-0001A")
        self.parcel = tax_parcel_from_pages(SUMMARY, pages, read_on=TODAY)

    def test_each_half_is_an_installment_with_its_due_date(self) -> None:
        [year] = self.parcel.years
        self.assertEqual(
            [(i.label, i.due_on, i.billed, i.paid, i.balance) for i in year.installments],
            [
                (
                    "1st half",
                    date(2026, 7, 28),
                    Decimal("2150.00"),
                    Decimal("2377.50"),
                    Decimal("0.00"),
                ),
                # December 5, 2026 is a Saturday.
                (
                    "2nd half",
                    date(2026, 12, 7),
                    Decimal("2150.00"),
                    Decimal("0.00"),
                    Decimal("2150.00"),
                ),
            ],
        )

    def test_interest_and_penalty_are_kept_apart_from_the_tax(self) -> None:
        [year] = self.parcel.years
        self.assertEqual(
            (year.billed, year.penalties, year.paid, year.balance),
            (Decimal("4300.00"), Decimal("227.50"), Decimal("2377.50"), Decimal("2150.00")),
        )

    def test_owed_before_the_due_date_is_due_and_after_it_past_due(self) -> None:
        self.assertIs(tax_status(self.parcel, date(2026, 12, 7)), TaxStatus.DUE)
        self.assertIs(tax_status(self.parcel, date(2026, 12, 8)), TaxStatus.PAST_DUE)

    def test_the_tab_is_read_with_the_parcel_number_as_the_site_writes_it(self) -> None:
        tab_url = next(url for url, _ in self.site.requests if "mode=tax_details" in url)
        self.assertEqual(parse_qs(urlparse(tab_url).query)["pin"], ["9999 01  0001A"])
        self.assertEqual(self.parcel.parcel_id, "9999 01 0001A")

    def test_the_sites_refresh_date_and_refunds_are_reported(self) -> None:
        self.assertEqual(self.parcel.data_as_of, date(2026, 10, 2))
        self.assertIn("pending refunds of $25.00", " ".join(self.parcel.notes))
        self.assertEqual(self.parcel.collector, "Sample County Treasurer")


class BilledAndPaymentsTests(unittest.TestCase):
    def _parcel(self, **tabs: str):
        site = _Site(
            found=BILLED_PAGE,
            tabs={"tax_all": BILLED_PAGE, "tax_collection": PAYMENTS_TAB, **tabs},
            disclaimer=True,
        )
        pages = _pages(BILLED, site, "99-90-001-234")
        return site, tax_parcel_from_pages(BILLED, pages, read_on=TODAY)

    def test_the_disclaimer_is_agreed_to_once_and_the_search_goes_on(self) -> None:
        site, parcel = self._parcel()

        agreements = [data for url, data in site.requests if "Disclaimer.aspx" in url and data]
        self.assertEqual(len(agreements), 1)
        self.assertIn("btAgree", agreements[0])
        self.assertEqual(parcel.parcel_id, "9990001234")

    def test_the_bill_less_its_payments_is_owed_by_equal_installments(self) -> None:
        _, parcel = self._parcel()

        [year] = parcel.years
        self.assertEqual(
            (year.tax_year, year.billed, year.paid, year.balance),
            (2025, Decimal("6000.00"), Decimal("3000.00"), Decimal("3000.00")),
        )
        self.assertEqual(
            [(i.label, i.due_on, i.balance) for i in year.installments],
            [
                ("1st installment", date(2026, 6, 1), Decimal("0.00")),
                ("2nd installment", date(2026, 9, 1), Decimal("3000.00")),
            ],
        )
        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)
        self.assertIn("equal share", " ".join(parcel.notes))

    def test_taxes_sold_at_tax_sale_are_owed_even_when_the_latest_year_is_paid(self) -> None:
        paid_in_full = PAYMENTS_TAB.replace(
            "<tr><td>2024</td><td>2,900.00</td>",
            "<tr><td>2025</td><td>3,000.00</td><td>.00</td><td>.00</td><td>.00</td><td>$3,000.00</td><td>08/28/2026</td><td>STD</td></tr>"
            "<tr><td>2024</td><td>2,900.00</td>",
            1,
        )
        _, parcel = self._parcel(tax_collection=paid_in_full, redemption=SOLD_TAB)

        sold = next(year for year in parcel.years if year.tax_year == 2023)
        self.assertEqual((sold.tax_sale, sold.balance), (True, Decimal("3410.00")))
        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)
        self.assertIn("sold at tax sale", " ".join(parcel.notes))

    def test_a_status_entry_that_cannot_be_read_leaves_the_balances_unknown(self) -> None:
        _, parcel = self._parcel(tax_status=FORFEITED_TAB)

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.UNKNOWN)
        self.assertTrue(all(year.balance is None for year in parcel.years))
        self.assertIn("couldn't be read", " ".join(parcel.notes))


class BalanceDueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = _Site(found=BALANCE_RESULTS, tabs={"": COPYRIGHT_ONLY, "tax_hist": BALANCE_TAB})
        pages = _pages(BALANCE, self.site, "999000000000000001")
        self.parcel = tax_parcel_from_pages(BALANCE, pages, read_on=TODAY)

    def test_each_year_and_the_current_halves_are_read(self) -> None:
        current, prior = self.parcel.years
        self.assertEqual(
            (current.tax_year, current.billed, current.penalties, current.paid, current.balance),
            (2025, Decimal("2000.00"), Decimal("140.00"), Decimal("1000.00"), Decimal("1140.00")),
        )
        self.assertEqual(
            [(i.label, i.due_on, i.balance) for i in current.installments],
            [
                ("1st half", date(2025, 11, 10), Decimal("0.00")),
                ("2nd half", date(2026, 4, 10), Decimal("1140.00")),
            ],
        )
        self.assertEqual((prior.tax_year, prior.balance), (2024, Decimal("0.00")))

    def test_a_half_owed_after_its_due_date_is_past_due(self) -> None:
        self.assertIs(tax_status(self.parcel, date(2026, 3, 1)), TaxStatus.DUE)
        self.assertIs(tax_status(self.parcel, TODAY), TaxStatus.PAST_DUE)

    def test_the_hit_supplies_the_address_and_the_county_its_quote_date(self) -> None:
        self.assertEqual(self.parcel.property_address, "100 EXAMPLE AVE NE")
        self.assertIn("$1,140.00 due, good through 31-OCT-2026", " ".join(self.parcel.notes))
        self.assertEqual(self.parcel.data_as_of, TODAY)


class CountyReceivableTests(unittest.TestCase):
    def _parcel(self, page: str = RECEIVABLE_PAGE):
        pages = _pages(RECEIVABLE, _Site(found=page, tabs={}), "99-00-00012-00")
        return tax_parcel_from_pages(RECEIVABLE, pages, read_on=TODAY)

    def test_each_bill_is_due_four_months_after_its_billing_date(self) -> None:
        parcel = self._parcel()

        current = parcel.years[0]
        [bill] = current.installments
        self.assertEqual(
            (bill.label, bill.due_on, bill.billed, bill.balance),
            ("County tax, original bill", date(2026, 6, 1), Decimal("1200.00"), Decimal("1320.00")),
        )
        self.assertEqual(current.penalties, Decimal("120.00"))
        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)

    def test_a_discount_explains_paying_less_than_the_bill(self) -> None:
        prior = self._parcel().years[1]

        self.assertEqual((prior.paid, prior.balance), (Decimal("1127.00"), Decimal("0.00")))
        self.assertEqual(prior.notes, ["Paid with a $23.00 discount."])

    def test_the_county_notes_and_footer_date_are_kept(self) -> None:
        parcel = self._parcel()

        self.assertEqual(parcel.notes, ["The county's site shows county tax only."])
        self.assertEqual(parcel.data_as_of, date(2026, 10, 3))

    def test_a_delinquent_listing_that_cannot_be_read_leaves_the_balances_unknown(self) -> None:
        page = RECEIVABLE_PAGE.replace(
            "No Outstanding Delinquent Amounts Found",
            "Claim returned to the tax claim bureau",
        )

        parcel = self._parcel(page)

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.UNKNOWN)
        self.assertIn("delinquent county tax", " ".join(parcel.notes))


class ParcelMatchTests(unittest.TestCase):
    def test_parcel_numbers_match_without_punctuation_or_leading_zeros(self) -> None:
        self.assertTrue(same_parcel("9999-01-0001A", "9999 01  0001A"))
        self.assertTrue(same_parcel("X01 00001 0001", "X01&#32;00001&#32;0001"))
        self.assertTrue(same_parcel("099-9000", "999000"))
        self.assertFalse(same_parcel("999000000000000002", "999000000000000001"))
        self.assertFalse(same_parcel("", ""))

    def test_a_neighbouring_parcel_from_a_wildcard_search_is_not_reported(self) -> None:
        site = _Site(found=BALANCE_RESULTS, tabs={"tax_hist": BALANCE_TAB})
        connector = build_auditor_source_connector(
            BALANCE, client=IasWorldAuditorClient(BALANCE, opener=site)
        )

        result = asyncio.run(
            connector.find_tax_status(SAMPLE, PropertyTaxQuery(parcel_id="999000000000000002"))
        )

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertEqual(result.records[0]["status"], "parcel_not_found")
        self.assertFalse(any("mode=tax_hist" in url for url, _ in site.requests))


class ConnectorTests(unittest.TestCase):
    def test_the_connector_answers_from_the_tax_tabs(self) -> None:
        site = _Site(found=BALANCE_RESULTS, tabs={"tax_hist": BALANCE_TAB})
        connector = build_auditor_source_connector(
            BALANCE, client=IasWorldAuditorClient(BALANCE, opener=site)
        )

        result = asyncio.run(
            connector.find_tax_status(SAMPLE, PropertyTaxQuery(parcel_id="999000000000000001"))
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        [record] = result.records
        self.assertEqual(record["total_balance"], "1140.00")
        self.assertEqual(record["source"]["refreshed"], "read live from the county's site")

    def test_a_site_that_cannot_be_reached_is_a_failure(self) -> None:
        class _Down:
            def open(self, request, timeout=None):
                raise URLError("connection refused")

        connector = build_auditor_source_connector(
            BALANCE, client=IasWorldAuditorClient(BALANCE, opener=_Down())
        )

        result = asyncio.run(
            connector.find_tax_status(SAMPLE, PropertyTaxQuery(parcel_id="999000000000000001"))
        )

        self.assertIs(result.status, SourceResultStatus.FAILED)


class DueDateTests(unittest.TestCase):
    def test_a_due_date_on_a_weekend_moves_to_the_monday(self) -> None:
        self.assertEqual(TaxDueDate(label="x", month=12, day=5).on(2026), date(2026, 12, 7))
        self.assertEqual(TaxDueDate(label="x", month=7, day=28).on(2026), date(2026, 7, 28))

    def test_a_due_date_can_fall_in_the_year_after_the_tax_year(self) -> None:
        due = TaxDueDate(label="x", month=6, day=1, years_after_tax_year=1)
        # June 1, 2025 is a Sunday.
        self.assertEqual(due.on(2024), date(2025, 6, 2))


if __name__ == "__main__":
    unittest.main()

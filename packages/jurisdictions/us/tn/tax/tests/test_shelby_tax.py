from __future__ import annotations

import json
import tomllib
import unittest
import urllib.parse
from datetime import date
from decimal import Decimal
from pathlib import Path

from titlemcp_us_tn_tax.adapters import ShelbyCountyTaxCertificateAdapter
from titlemcp_us_tn_tax.client import (
    PARCEL_URL,
    ShelbyTrusteeClient,
    TrusteeError,
    parcel_candidates,
)
from titlemcp_us_tn_tax.connector import ShelbyCountyTaxConnector
from titlemcp_us_tn_tax.manifest import capability_manifest
from titlemcp_us_tn_tax.mapping import tax_parcel

from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
from title_mcp.domain.tax import PropertyTaxQuery, TaxStatus, tax_status
from title_mcp.sources import PropertyTaxSource, SourceKind, SourceQuery, SourceResultStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PACKAGE_ROOT / "tests" / "fixtures"
PARCELS = json.loads((FIXTURES / "parcels.json").read_text())
CURRENT, DELINQUENT, DISAGREES, OTHER_GROUP = PARCELS
SHELBY = Jurisdiction(state="TN", county="Shelby County")
TODAY = date(2026, 10, 11)


class _Fetch:
    """Answers like the parcel page: the number with single spaces, or a 404."""

    def __init__(self, *, status: int | None = None, pages: dict | None = None) -> None:
        self.urls: list[str] = []
        self.status = status
        self.pages = PARCELS if pages is None else pages

    def __call__(self, url: str) -> tuple[int, object]:
        self.urls.append(url)
        if self.status is not None:
            return self.status, None
        asked = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["parcel"][0]
        for parcel, page in self.pages.items():
            if " ".join(parcel.split()) == asked:
                return 200, page
        return 404, None


class ParcelNumberTests(unittest.TestCase):
    def test_spacing_and_dashes_become_one_space(self) -> None:
        for written in ("099999 00001", "099999   00001", " 099999-00001 "):
            with self.subTest(written=written):
                self.assertEqual(parcel_candidates(written), ["099999 00001"])

    def test_a_number_without_spaces_splits_before_its_last_five_or_six(self) -> None:
        self.assertEqual(parcel_candidates("09999900001"), ["099999 00001", "09999 900001"])
        self.assertEqual(parcel_candidates("099999a00001"), ["099999A 00001", "099999 A00001"])


class ClientTests(unittest.TestCase):
    def test_a_parcel_is_read_from_its_page(self) -> None:
        fetch = _Fetch()

        page = ShelbyTrusteeClient(fetch=fetch).parcel("099999   00001")

        self.assertEqual(fetch.urls, [f"{PARCEL_URL}?parcel=099999+00001"])
        self.assertEqual(page["mergedBillData"][0]["billNumber"], 26900001)

    def test_a_number_without_spaces_tries_both_splits(self) -> None:
        fetch = _Fetch()

        page = ShelbyTrusteeClient(fetch=fetch).parcel("09999900001")

        self.assertEqual(len(fetch.urls), 2)
        self.assertEqual(page["mergedBillData"][0]["billNumber"], 26900001)

    def test_both_splits_existing_is_ambiguous(self) -> None:
        pages = {"099999  00001": PARCELS[CURRENT], "09999  900001": PARCELS[CURRENT]}

        self.assertIsNone(ShelbyTrusteeClient(fetch=_Fetch(pages=pages)).parcel("09999900001"))

    def test_a_page_for_another_parcel_is_not_taken(self) -> None:
        pages = {"099999  00009": PARCELS[CURRENT]}

        self.assertIsNone(ShelbyTrusteeClient(fetch=_Fetch(pages=pages)).parcel("099999 00009"))

    def test_a_parcel_the_trustee_does_not_have_is_none(self) -> None:
        self.assertIsNone(ShelbyTrusteeClient(fetch=_Fetch()).parcel("099999 00099"))

    def test_an_error_page_raises(self) -> None:
        with self.assertRaises(TrusteeError):
            ShelbyTrusteeClient(fetch=_Fetch(status=500)).parcel("099999 00001")


class MappingTests(unittest.TestCase):
    def test_this_years_bill_is_owed_but_not_yet_due(self) -> None:
        parcel = tax_parcel(PARCELS[CURRENT])

        self.assertEqual([year.tax_year for year in parcel.years], [2026, 2025])
        current, last = parcel.years
        self.assertEqual(
            (current.billed, current.paid, current.balance),
            (Decimal("1100.00"), Decimal("0.00"), Decimal("1100.00")),
        )
        self.assertEqual(current.installments[0].due_on, date(2027, 2, 28))
        self.assertEqual(current.installments[0].label, "bill 26900001")
        self.assertEqual((last.paid, last.balance), (Decimal("1000.00"), Decimal("0.00")))
        self.assertEqual(parcel.parcel_id, "099999 00001")
        self.assertEqual(parcel.taxpayer_name, "SAMPLE OWNER LLC")
        self.assertEqual(parcel.property_address, "100 SAMPLE AVE")
        # The billing system's 71 days past due count from the August bill date.
        self.assertIsNone(current.delinquent)
        self.assertIs(tax_status(parcel, TODAY), TaxStatus.DUE)
        self.assertIs(tax_status(parcel, date(2027, 3, 1)), TaxStatus.PAST_DUE)
        notes = " ".join(parcel.notes)
        self.assertIn("BE (2019)", notes)
        self.assertIn("City of Memphis", notes)
        self.assertIn("67-5-2010", notes)

    def test_last_years_unpaid_bill_is_past_due_with_interest_and_a_tax_sale(self) -> None:
        parcel = tax_parcel(PARCELS[DELINQUENT])

        last = parcel.years[1]
        self.assertEqual(last.balance, Decimal("1120.00"))
        self.assertEqual(last.penalties, Decimal("120.00"))
        self.assertIn("scheduled for tax sale (code TS)", parcel.notes[0])
        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)

    def test_balances_that_disagree_leave_the_parcel_unknown_not_paid(self) -> None:
        parcel = tax_parcel(PARCELS[DISAGREES])

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.UNKNOWN)
        self.assertIn("balances disagree", " ".join(parcel.notes))

    def test_bills_in_a_group_it_does_not_read_leave_the_parcel_unknown(self) -> None:
        parcel = tax_parcel(PARCELS[OTHER_GROUP])

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.UNKNOWN)
        self.assertTrue(all(year.balance is None for year in parcel.years))


def _key(parcel_id: str) -> str:
    return "".join(parcel_id.split())


class _FakeTrustee:
    def __init__(self, *, fail: bool = False) -> None:
        self.asked: list[str] = []
        self.fail = fail

    def parcel(self, parcel_id: str) -> dict | None:
        if self.fail:
            raise OSError("connection reset")
        self.asked.append(parcel_id)
        return next(
            (page for key, page in PARCELS.items() if _key(key) == _key(parcel_id)),
            None,
        )


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def _find(self, parcel_id: str, client=None):
        connector = ShelbyCountyTaxConnector(client=client or _FakeTrustee())
        return await connector.find_tax_status(SHELBY, PropertyTaxQuery(parcel_id=parcel_id))

    def test_it_covers_shelby_county_only(self) -> None:
        connector = ShelbyCountyTaxConnector(client=_FakeTrustee())

        self.assertIsInstance(connector, PropertyTaxSource)
        self.assertTrue(connector.supports(SHELBY, SourceKind.TAX_AUTHORITY))
        self.assertFalse(connector.supports(Jurisdiction(state="TN", county="Davidson County")))
        self.assertFalse(connector.supports(Jurisdiction(state="AL", county="Shelby County")))

    async def test_a_parcel_becomes_a_canonical_record(self) -> None:
        result = await self._find("099999 00002")

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.property_tax_status")
        self.assertEqual(record["parcel_id"], "099999 00002")
        self.assertEqual(record["status"], "past_due")
        self.assertEqual(record["total_balance"], "2220.00")
        self.assertEqual(
            record["source"]["source_url"],
            "https://apps2.shelbycountytrustee.com/Parcel?parcel=099999%2000002",
        )
        self.assertTrue(record["requires_human_review"])
        # The Tax Query gives no extract date, so the answer says to confirm.
        self.assertIsNone(record["source"]["data_as_of"])
        self.assertIn("doesn't say when", " ".join(record["notes"]))

    async def test_a_parcel_the_trustee_does_not_have_is_no_results(self) -> None:
        result = await self._find("099999 00099")

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertEqual(result.records[0]["status"], "parcel_not_found")

    async def test_the_tax_query_failing_is_a_failed_result(self) -> None:
        result = await self._find("099999 00001", client=_FakeTrustee(fail=True))

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("connection reset", result.warnings[0])

    async def test_a_source_query_needs_a_parcel(self) -> None:
        connector = ShelbyCountyTaxConnector(client=_FakeTrustee())

        result = await connector.query(
            SourceQuery(jurisdiction=SHELBY, kind=SourceKind.TAX_AUTHORITY, criteria={})
        )

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)


class ContractTests(unittest.IsolatedAsyncioTestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.TAX_CERTIFICATE, manifest.workflow_kinds)

    def test_entry_points_name_the_classes_that_exist(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            entry_points = tomllib.load(pyproject_file)["project"]["entry-points"]

        self.assertEqual(
            entry_points["title_mcp.sources"]["us_tn_tax"],
            capability_manifest().entry_points["title_mcp.sources"],
        )
        self.assertEqual(
            entry_points["title_mcp.adapters"]["us_tn_tax"],
            capability_manifest().entry_points["title_mcp.adapters"],
        )

    async def test_the_plan_reads_the_county_bills_and_sends_city_tax_to_the_city(self) -> None:
        adapter = ShelbyCountyTaxCertificateAdapter()
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.TAX_CERTIFICATE,
            jurisdiction=SHELBY,
        )

        plan = await adapter.plan(request)

        self.assertTrue(adapter.supports(SHELBY))
        self.assertFalse(adapter.supports(Jurisdiction(state="TN", county="Knox County")))
        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "property_tax_status_search")
        self.assertIn("City of Memphis", plan.steps[1].description)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tomllib
import unittest
import urllib.parse
from datetime import date
from decimal import Decimal
from pathlib import Path

from titlemcp_us_ca_tax.adapters import ContraCostaTaxCertificateAdapter
from titlemcp_us_ca_tax.client import APN_LOOKUP_URL, ContraCostaLookupClient, TaxLookupError
from titlemcp_us_ca_tax.connector import ContraCostaTaxConnector
from titlemcp_us_ca_tax.manifest import capability_manifest
from titlemcp_us_ca_tax.mapping import apn_digits, tax_parcel

from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
from title_mcp.domain.tax import PropertyTaxQuery, TaxStatus, tax_status
from title_mcp.sources import PropertyTaxSource, SourceKind, SourceQuery, SourceResultStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = json.loads((PACKAGE_ROOT / "tests" / "fixtures" / "lookups.json").read_text())
CONTRA_COSTA = Jurisdiction(state="CA", county="Contra Costa County")
LOOKUP_DAY = date(2026, 10, 9)


class ApnTests(unittest.TestCase):
    def test_the_usual_ways_of_writing_an_apn_become_its_digits(self) -> None:
        cases = {
            "999-010-001-1": "9990100011",
            "9990100011": "9990100011",
            "999 010 001 1": "9990100011",
            # Without its check digit, as the county's lookup also accepts.
            "999-010-001": "999010001",
        }
        for written, digits in cases.items():
            with self.subTest(written=written):
                self.assertEqual(apn_digits(written), digits)

    def test_something_else_is_not_an_apn(self) -> None:
        for written in ("12-34", "999-010-001-11-2", "Main Street"):
            with self.subTest(written=written):
                self.assertIsNone(apn_digits(written))


class _Fetch:
    def __init__(self, *, status: int | None = None, payload: object = None) -> None:
        self.urls: list[str] = []
        self.status = status
        self.payload = payload

    def __call__(self, url: str) -> tuple[int, object]:
        self.urls.append(url)
        if self.status is not None:
            return self.status, self.payload
        apn = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["apn"][0]
        if apn in LOOKUPS:
            return 200, LOOKUPS[apn]
        return 400, {"displayMessage": "Invalid Parcel Number"}


class ClientTests(unittest.TestCase):
    def test_a_parcel_is_looked_up_by_apn(self) -> None:
        fetch = _Fetch()

        payload = ContraCostaLookupClient(fetch=fetch).parcel("9990100011")

        self.assertEqual(fetch.urls, [f"{APN_LOOKUP_URL}?apn=9990100011"])
        self.assertEqual(payload["details"]["apn"], "999-010-001-1")

    def test_an_apn_the_county_rejects_or_lacks_is_none(self) -> None:
        for status in (400, 404):
            with self.subTest(status=status):
                client = ContraCostaLookupClient(
                    fetch=_Fetch(status=status, payload={"displayMessage": "Not found"})
                )
                self.assertIsNone(client.parcel("9990100099"))

    def test_any_other_answer_raises_with_the_countys_message(self) -> None:
        client = ContraCostaLookupClient(
            fetch=_Fetch(status=503, payload={"displayMessage": "Try again later"})
        )

        with self.assertRaisesRegex(TaxLookupError, "503: Try again later"):
            client.parcel("9990100011")

    def test_an_address_list_instead_of_a_parcel_raises(self) -> None:
        client = ContraCostaLookupClient(
            fetch=_Fetch(status=200, payload={"responseType": "Address", "addresses": []})
        )

        with self.assertRaises(TaxLookupError):
            client.parcel("9990100011")


class MappingTests(unittest.TestCase):
    def test_the_current_year_is_owed_but_not_yet_delinquent(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100011"])

        self.assertEqual([year.tax_year for year in parcel.years], [2026, 2025])
        current = parcel.years[0]
        self.assertEqual(
            [(i.label, i.due_on, i.balance) for i in current.installments],
            [
                ("1st installment", date(2026, 12, 10), Decimal("3100.00")),
                ("2nd installment", date(2027, 4, 12), Decimal("3100.00")),
            ],
        )
        self.assertEqual(parcel.years[1].paid, Decimal("6000.00"))
        self.assertEqual(parcel.years[1].balance, Decimal("0.00"))
        self.assertEqual(parcel.parcel_id, "999-010-001-1")
        self.assertEqual(parcel.property_address, "100 SAMPLE ST, MARTINEZ")
        self.assertEqual(parcel.data_as_of, LOOKUP_DAY)
        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.DUE)
        self.assertIs(tax_status(parcel, date(2026, 12, 11)), TaxStatus.PAST_DUE)

    def test_a_delinquent_installment_is_past_due_with_its_penalty_in_the_balance(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100022"])

        [year] = parcel.years
        self.assertTrue(year.delinquent)
        self.assertEqual(year.balance, Decimal("2210.00"))
        # The delinquent amount carries the penalty, so the bill itself isn't known.
        self.assertIsNone(year.billed)
        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.PAST_DUE)

    def test_a_redemption_bill_is_a_delinquent_earlier_year(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100033"])

        redemption = next(year for year in parcel.years if year.tax_year == 2023)
        self.assertTrue(redemption.delinquent)
        self.assertEqual(redemption.balance, Decimal("4812.55"))
        self.assertEqual(redemption.installments[0].label, "redemption bill 2324-000303")
        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.PAST_DUE)

    def test_a_status_it_does_not_read_leaves_the_parcel_unknown_not_paid(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100044"])

        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.UNKNOWN)
        self.assertTrue(all(year.balance is None for year in parcel.years))
        self.assertIn("status PARTIAL", parcel.notes[0])

    def test_a_delinquency_flag_with_nothing_delinquent_shown_is_unknown(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100055"])

        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.UNKNOWN)
        self.assertIn("delinquency flag", parcel.notes[0])

    def test_a_pending_payment_counts_as_owed_and_a_supplemental_bill_is_a_charge(self) -> None:
        parcel = tax_parcel(LOOKUPS["9990100066"])

        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.DUE)
        current = parcel.years[0]
        self.assertEqual(current.balance, Decimal("6200.00"))
        self.assertIsNone(current.paid)
        [charge] = parcel.other_charges
        self.assertEqual(
            (charge.label, charge.balance),
            ("Supplemental bill 2526-800606 for 2025-26", Decimal("1280.00")),
        )
        notes = " ".join(parcel.notes)
        self.assertIn("10/05/2026", notes)
        self.assertIn("delinquent after November 30, 2026", notes)

    def test_a_delinquent_supplemental_bill_joins_its_year(self) -> None:
        payload = json.loads(json.dumps(LOOKUPS["9990100066"]))
        payload["installments"][2]["isDelinquent"] = True

        parcel = tax_parcel(payload)

        self.assertEqual(parcel.other_charges, [])
        supplemental_year = next(year for year in parcel.years if year.tax_year == 2025)
        self.assertTrue(supplemental_year.delinquent)
        self.assertIs(tax_status(parcel, LOOKUP_DAY), TaxStatus.PAST_DUE)


class _FakeLookup:
    def __init__(self, *, fail: bool = False) -> None:
        self.asked: list[str] = []
        self.fail = fail

    def parcel(self, apn: str) -> dict | None:
        if self.fail:
            raise OSError("connection reset")
        self.asked.append(apn)
        return LOOKUPS.get(apn)


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def _find(self, parcel_id: str, client=None):
        connector = ContraCostaTaxConnector(client=client or _FakeLookup())
        return await connector.find_tax_status(CONTRA_COSTA, PropertyTaxQuery(parcel_id=parcel_id))

    def test_it_covers_contra_costa_county_only(self) -> None:
        connector = ContraCostaTaxConnector(client=_FakeLookup())

        self.assertIsInstance(connector, PropertyTaxSource)
        self.assertTrue(connector.supports(CONTRA_COSTA, SourceKind.TAX_AUTHORITY))
        self.assertFalse(connector.supports(Jurisdiction(state="CA", county="Orange County")))
        self.assertFalse(connector.supports(Jurisdiction(state="TX", county="Contra Costa County")))

    async def test_a_parcel_becomes_a_canonical_record_with_the_lookups_date(self) -> None:
        fake = _FakeLookup()

        result = await self._find("999-010-002-2", client=fake)

        self.assertEqual(fake.asked, ["9990100022"])
        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.property_tax_status")
        self.assertEqual(record["parcel_id"], "999-010-002-2")
        self.assertEqual(record["status"], "past_due")
        self.assertEqual(record["total_balance"], "2210.00")
        self.assertEqual(record["source"]["data_as_of"], "2026-10-09")
        self.assertEqual(
            record["source"]["source_url"], "https://taxcolp.cccttc.us/lookup/?apn=9990100022"
        )
        self.assertTrue(record["requires_human_review"])
        self.assertIn("November 1", " ".join(record["notes"]))

    async def test_a_parcel_the_county_does_not_have_is_no_results(self) -> None:
        result = await self._find("999-010-009-9")

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertEqual(result.records[0]["status"], "parcel_not_found")

    async def test_something_that_is_not_an_apn_asks_for_one(self) -> None:
        fake = _FakeLookup()

        result = await self._find("100 Sample St", client=fake)

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertEqual(fake.asked, [])
        self.assertIn("123-456-789-1", result.warnings[0])

    async def test_the_lookup_failing_is_a_failed_result(self) -> None:
        result = await self._find("999-010-001-1", client=_FakeLookup(fail=True))

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("connection reset", result.warnings[0])

    async def test_a_source_query_needs_a_parcel(self) -> None:
        connector = ContraCostaTaxConnector(client=_FakeLookup())

        result = await connector.query(
            SourceQuery(jurisdiction=CONTRA_COSTA, kind=SourceKind.TAX_AUTHORITY, criteria={})
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
            entry_points["title_mcp.sources"]["us_ca_tax"],
            capability_manifest().entry_points["title_mcp.sources"],
        )
        self.assertEqual(
            entry_points["title_mcp.adapters"]["us_ca_tax"],
            capability_manifest().entry_points["title_mcp.adapters"],
        )

    async def test_the_plan_reads_the_lookup_then_confirms_with_the_collector(self) -> None:
        adapter = ContraCostaTaxCertificateAdapter()
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.TAX_CERTIFICATE,
            jurisdiction=CONTRA_COSTA,
        )

        plan = await adapter.plan(request)

        self.assertTrue(adapter.supports(CONTRA_COSTA))
        self.assertFalse(adapter.supports(Jurisdiction(state="CA", county="Alameda County")))
        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "property_tax_status_search")


if __name__ == "__main__":
    unittest.main()

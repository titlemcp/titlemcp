from __future__ import annotations

import json
import tomllib
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from titlemcp_us_dc_tax.adapters import DistrictOfColumbiaTaxCertificateAdapter
from titlemcp_us_dc_tax.client import FALLBACK_SERVICE_URL, ITEM_URL, ArcGISError, ExtractClient
from titlemcp_us_dc_tax.connector import DATASET_URL, DistrictOfColumbiaTaxConnector
from titlemcp_us_dc_tax.manifest import capability_manifest
from titlemcp_us_dc_tax.mapping import ssl_candidates, tax_parcel

from title_mcp.domain.models import Jurisdiction, OrderRef, WorkflowKind, WorkflowRequest
from title_mcp.domain.tax import PropertyTaxQuery, TaxStatus, tax_status
from title_mcp.sources import PropertyTaxSource, SourceKind, SourceQuery, SourceResultStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PACKAGE_ROOT / "tests" / "fixtures"
ROWS = [
    f["attributes"] for f in json.loads((FIXTURES / "extract_rows.json").read_text())["features"]
]
OWED, PAID, SOLD = ROWS
DC = Jurisdiction(state="DC", county="District of Columbia")
AFTER_SECOND_HALF = date(2026, 10, 10)


class SslTests(unittest.TestCase):
    def test_square_and_lot_are_padded_the_way_the_extract_stores_them(self) -> None:
        for written in ("9999 1", "9999-0001", "9999/0001", "Square 9999 Lot 1", "9999    0001"):
            with self.subTest(written=written):
                self.assertEqual(ssl_candidates(written)[0], "9999    0001")

    def test_a_suffix_keeps_its_column(self) -> None:
        self.assertEqual(ssl_candidates("9999N 0002")[0], "9999N   0002")
        self.assertEqual(ssl_candidates("9999 N 0002")[0], "9999N   0002")

    def test_other_parcel_kinds_are_matched_as_given(self) -> None:
        self.assertEqual(ssl_candidates("par 99990003"), ["PAR 99990003"])


class _Fetch:
    def __init__(self, *, item_fails: bool = False, payload: dict | None = None) -> None:
        self.urls: list[str] = []
        self.item_fails = item_fails
        self.payload = payload

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if url == ITEM_URL:
            if self.item_fails:
                raise OSError("item unavailable")
            return json.loads((FIXTURES / "item.json").read_text())
        if url.endswith("?f=json"):
            return json.loads((FIXTURES / "layer.json").read_text())
        return self.payload or json.loads((FIXTURES / "extract_rows.json").read_text())


class ClientTests(unittest.TestCase):
    def test_the_layer_is_found_through_the_item_and_its_edit_date_read(self) -> None:
        fetch = _Fetch()
        client = ExtractClient(fetch=fetch)

        rows = client.parcels(["9999    0001", "O'NEIL"])

        self.assertEqual(len(rows), 3)
        query_url = fetch.urls[-1]
        self.assertTrue(
            query_url.startswith(
                "https://services.example.test/arcgis/rest/services/ITSPE_10012026/FeatureServer/0/query?"
            )
        )
        self.assertIn("O%27%27NEIL", query_url)
        self.assertEqual(client.last_edited(), date(2026, 10, 9))

    def test_the_known_service_is_used_when_the_item_cannot_be_read(self) -> None:
        client = ExtractClient(fetch=_Fetch(item_fails=True))

        self.assertEqual(client.layer_url(), f"{FALLBACK_SERVICE_URL}/0")

    def test_an_error_answer_raises(self) -> None:
        client = ExtractClient(fetch=_Fetch(payload={"error": {"message": "Invalid query"}}))

        with self.assertRaises(ArcGISError):
            client.parcels(["9999    0001"])


class MappingTests(unittest.TestCase):
    def test_the_current_year_is_two_halves_with_their_due_dates(self) -> None:
        parcel = tax_parcel(OWED, data_as_of=date(2026, 10, 9))

        self.assertEqual([year.tax_year for year in parcel.years], [2026, 2025, 2024])
        current = parcel.years[0]
        self.assertEqual(
            [(i.label, i.due_on, i.balance) for i in current.installments],
            [
                ("1st half", date(2026, 3, 31), Decimal("690.00")),
                ("2nd half", date(2026, 9, 15), Decimal("600.00")),
            ],
        )
        self.assertEqual(current.billed, Decimal("1200.00"))
        self.assertEqual(current.penalties, Decimal("90.00"))
        self.assertEqual(current.balance, Decimal("1290.00"))
        self.assertEqual(parcel.years[1].balance, Decimal("110.00"))
        self.assertEqual(parcel.taxpayer_name, "SAMPLE OWNER")
        self.assertIs(tax_status(parcel, AFTER_SECOND_HALF), TaxStatus.PAST_DUE)

    def test_a_paid_parcel_lists_its_assessment_and_owes_nothing(self) -> None:
        parcel = tax_parcel(PAID, data_as_of=None)

        self.assertIs(tax_status(parcel, AFTER_SECOND_HALF), TaxStatus.PAID)
        [charge] = parcel.other_charges
        self.assertEqual(
            (charge.label, charge.billed, charge.balance),
            ("Business improvement district", Decimal("150.00"), Decimal("0.00")),
        )

    def test_years_sold_at_tax_sale_are_flagged(self) -> None:
        parcel = tax_parcel(SOLD, data_as_of=None)

        flags = {year.tax_year: year.tax_sale for year in parcel.years}
        self.assertEqual(flags, {2026: None, 2025: True, 2024: True})


class _FakeExtract:
    def __init__(self, *, fail: bool = False) -> None:
        self.asked: list[list[str]] = []
        self.fail = fail

    def parcels(self, ssl_values: list[str]) -> list[dict]:
        if self.fail:
            raise OSError("connection reset")
        self.asked.append(ssl_values)
        return [row for row in ROWS if row["SSL"] in ssl_values]

    def last_edited(self) -> date:
        return date(2026, 10, 9)


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def _find(self, parcel_id: str, client=None):
        connector = DistrictOfColumbiaTaxConnector(client=client or _FakeExtract())
        return await connector.find_tax_status(DC, PropertyTaxQuery(parcel_id=parcel_id))

    def test_it_reads_tax_status_for_the_district_however_the_county_is_named(self) -> None:
        connector = DistrictOfColumbiaTaxConnector(client=_FakeExtract())

        self.assertIsInstance(connector, PropertyTaxSource)
        for county in ("District of Columbia", "District of Columbia County", "Washington"):
            with self.subTest(county=county):
                self.assertTrue(
                    connector.supports(
                        Jurisdiction(state="DC", county=county), SourceKind.TAX_AUTHORITY
                    )
                )
        self.assertFalse(connector.supports(Jurisdiction(state="MD", county="Montgomery County")))

    async def test_a_parcel_becomes_a_canonical_record_with_the_extracts_date(self) -> None:
        result = await self._find("9999 1")

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.property_tax_status")
        self.assertEqual(record["parcel_id"], "9999    0001")
        self.assertEqual(record["status"], "past_due")
        self.assertEqual(record["total_balance"], "1400.00")
        self.assertEqual(record["source"]["data_as_of"], "2026-10-09")
        self.assertEqual(record["source"]["refreshed"], "weekdays")
        self.assertEqual(record["source"]["source_url"], DATASET_URL)
        self.assertIn("47-811", " ".join(record["notes"]))

    async def test_a_parcel_not_in_the_extract_is_no_results(self) -> None:
        result = await self._find("1 1")

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertEqual(result.records[0]["status"], "parcel_not_found")

    async def test_the_extract_failing_is_a_failed_result(self) -> None:
        result = await self._find("9999 1", client=_FakeExtract(fail=True))

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("connection reset", result.warnings[0])

    async def test_a_source_query_needs_a_parcel(self) -> None:
        connector = DistrictOfColumbiaTaxConnector(client=_FakeExtract())

        result = await connector.query(
            SourceQuery(jurisdiction=DC, kind=SourceKind.TAX_AUTHORITY, criteria={})
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

    async def test_the_plan_reads_the_extract_then_confirms_with_the_office(self) -> None:
        adapter = DistrictOfColumbiaTaxCertificateAdapter()
        request = WorkflowRequest(
            order=OrderRef(file_number="SAMPLE-1"),
            kind=WorkflowKind.TAX_CERTIFICATE,
            jurisdiction=DC,
        )

        plan = await adapter.plan(request)

        self.assertTrue(adapter.supports(DC))
        self.assertFalse(adapter.supports(Jurisdiction(state="VA", county="Fairfax County")))
        self.assertTrue(plan.required_review)
        self.assertEqual(plan.steps[0].metadata["tool"], "property_tax_status_search")


if __name__ == "__main__":
    unittest.main()

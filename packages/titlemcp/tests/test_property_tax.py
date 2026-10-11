from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.tax import (
    PropertyTaxQuery,
    TaxCharge,
    TaxInstallment,
    TaxParcel,
    TaxStatus,
    TaxYear,
    tax_status,
    total_balance,
)
from title_mcp.mcp.server import create_mcp_server
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import (
    PropertyTaxSource,
    SourceDescriptor,
    SourceKind,
    SourceResult,
    SourceResultStatus,
    tax_source_result,
)
from title_mcp.state.memory import InMemoryWorkflowRepository

TODAY = date(2026, 10, 10)
DESCRIPTOR = SourceDescriptor(
    source_id="fake-sample-tax",
    name="Sample County Treasurer",
    kind=SourceKind.TAX_AUTHORITY,
    jurisdiction_scope=JurisdictionScope(country="US", state="XX", county="Sample County"),
    base_url="https://tax.sample.example",
)
SAMPLE = Jurisdiction(state="XX", county="Sample County")


def _year(tax_year: int, *, billed="1000.00", paid="1000.00", balance="0.00", **kwargs) -> TaxYear:
    return TaxYear(
        tax_year=tax_year,
        billed=Decimal(billed),
        paid=Decimal(paid),
        balance=Decimal(balance),
        **kwargs,
    )


def _parcel(*years: TaxYear, **kwargs) -> TaxParcel:
    return TaxParcel(parcel_id="0000-TEST-01", years=list(years), **kwargs)


class TaxStatusTests(unittest.TestCase):
    def test_nothing_owed_is_paid(self) -> None:
        parcel = _parcel(_year(2026), _year(2025))

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAID)
        self.assertEqual(total_balance(parcel), Decimal("0.00"))

    def test_an_installment_not_yet_due_is_due(self) -> None:
        year = _year(
            2026,
            paid="500.00",
            balance="500.00",
            installments=[
                TaxInstallment(label="1st half", due_on=date(2026, 3, 31), balance=Decimal(0)),
                TaxInstallment(label="2nd half", due_on=date(2026, 11, 15), balance=Decimal(500)),
            ],
        )

        self.assertIs(tax_status(_parcel(year), TODAY), TaxStatus.DUE)

    def test_an_installment_owed_after_its_due_date_is_past_due(self) -> None:
        year = _year(
            2026,
            paid="0.00",
            balance="1000.00",
            installments=[
                TaxInstallment(label="1st half", due_on=date(2026, 3, 31), balance=Decimal(500)),
            ],
        )

        self.assertIs(tax_status(_parcel(year), TODAY), TaxStatus.PAST_DUE)

    def test_a_balance_on_an_earlier_year_is_past_due(self) -> None:
        parcel = _parcel(_year(2026), _year(2024, paid="0.00", balance="980.00"))

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)
        self.assertEqual(total_balance(parcel), Decimal("980.00"))

    def test_the_collectors_own_delinquent_flag_counts(self) -> None:
        parcel = _parcel(_year(2026, paid="0.00", balance="1000.00", delinquent=True))

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.PAST_DUE)

    def test_a_balance_without_dates_is_due_not_guessed_past_due(self) -> None:
        parcel = _parcel(_year(2026, paid="0.00", balance="1000.00"))

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.DUE)

    def test_an_assessment_owed_beside_paid_tax_is_due(self) -> None:
        parcel = _parcel(
            _year(2026),
            other_charges=[TaxCharge(label="Special assessment", balance=Decimal("75.00"))],
        )

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.DUE)
        self.assertEqual(total_balance(parcel), Decimal("75.00"))

    def test_no_balances_at_all_is_unknown(self) -> None:
        parcel = _parcel(TaxYear(tax_year=2026, billed=Decimal("1000.00")))

        self.assertIs(tax_status(parcel, TODAY), TaxStatus.UNKNOWN)
        self.assertIsNone(total_balance(parcel))


class QueryTests(unittest.TestCase):
    def test_a_parcel_number_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            PropertyTaxQuery(parcel_id="   ")

    def test_the_parcel_number_is_kept_as_given(self) -> None:
        self.assertEqual(PropertyTaxQuery(parcel_id=" 0000-TEST-01 ").parcel_id, "0000-TEST-01")


class RecordTests(unittest.TestCase):
    def _result(self, parcel: TaxParcel | None) -> SourceResult:
        return tax_source_result(
            descriptor=DESCRIPTOR,
            jurisdiction=SAMPLE,
            query=PropertyTaxQuery(parcel_id="0000-TEST-01"),
            parcel=parcel,
            refreshed="weekdays",
            today=TODAY,
        )

    def test_the_parcel_becomes_a_canonical_record_marked_for_review(self) -> None:
        parcel = _parcel(
            _year(2026, paid="500.00", balance="500.00"),
            taxpayer_name="SAMPLE TAXPAYER",
            data_as_of=date(2026, 10, 9),
        )

        result = self._result(parcel)

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.property_tax_status")
        self.assertEqual(record["record_type"], "property_tax_status")
        self.assertEqual(record["status"], "due")
        self.assertEqual(record["total_balance"], "500.00")
        self.assertEqual(record["source"]["data_as_of"], "2026-10-09")
        self.assertEqual(record["source"]["refreshed"], "weekdays")
        self.assertEqual(record["years"][0]["tax_year"], 2026)
        self.assertEqual(result.citations[0].uri, "https://tax.sample.example")

    def test_old_data_is_called_out(self) -> None:
        result = self._result(_parcel(_year(2026), data_as_of=date(2026, 8, 15)))

        self.assertIn("2026-08-15, 56 days ago", " ".join(result.warnings))

    def test_data_without_a_date_says_so(self) -> None:
        result = self._result(_parcel(_year(2026)))

        self.assertIn("doesn't say when", " ".join(result.warnings))

    def test_a_parcel_the_collector_does_not_have_is_no_results(self) -> None:
        result = self._result(None)

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertEqual(result.records[0]["status"], "parcel_not_found")


class _FakeTaxSource:
    def __init__(self, county: str = "Sample County", state: str = "XX") -> None:
        self.source_id = f"fake-{county.lower().replace(' ', '-')}-tax"
        self.descriptor = SourceDescriptor(
            source_id=self.source_id,
            name=f"{county} Treasurer",
            kind=SourceKind.TAX_AUTHORITY,
            jurisdiction_scope=JurisdictionScope(country="US", state=state, county=county),
        )
        self.queries: list[PropertyTaxQuery] = []

    def supports(self, jurisdiction, kind=None) -> bool:
        return (kind is None or kind == SourceKind.TAX_AUTHORITY) and (
            self.descriptor.jurisdiction_scope.matches(jurisdiction)
        )

    async def query(self, query):  # pragma: no cover - not used by the tax tool
        raise NotImplementedError

    async def find_tax_status(self, jurisdiction, query) -> SourceResult:
        self.queries.append(query)
        return SourceResult(source_id=self.source_id, status=SourceResultStatus.SUCCEEDED)


class PropertyTaxToolTests(unittest.IsolatedAsyncioTestCase):
    def _server(self, *connectors):
        settings = TitleMCPSettings(
            environment="test",
            log_json=False,
            state_backend="memory",
            load_entry_point_adapters=False,
            load_entry_point_capabilities=False,
            load_entry_point_sources=False,
            load_entry_point_vendors=False,
            load_entry_point_plugins=False,
            load_entry_point_toolsets=False,
        )
        platform = TitleMCPPlatform(settings=settings, repository=InMemoryWorkflowRepository())
        for connector in connectors:
            platform.sources.register(connector)
        return create_mcp_server(settings, platform)

    async def _call(self, server, **arguments) -> dict:
        result = await server.call_tool("property_tax_status_search", arguments)
        return json.loads(result.content[0].text)

    def test_a_connector_that_reads_tax_status_is_recognized(self) -> None:
        self.assertIsInstance(_FakeTaxSource(), PropertyTaxSource)

    async def test_the_county_is_routed_whether_or_not_it_says_county(self) -> None:
        source = _FakeTaxSource()
        server = self._server(source)

        for county in ("Sample", "Sample County"):
            with self.subTest(county=county):
                result = await self._call(
                    server, state="XX", county=county, parcel_id="0000-TEST-01"
                )
                self.assertEqual(result["status"], "succeeded")
        self.assertEqual(source.queries[0].parcel_id, "0000-TEST-01")

    async def test_a_place_that_is_not_a_county_is_routed_as_named(self) -> None:
        source = _FakeTaxSource(county="Sample District", state="YY")
        server = self._server(source)

        result = await self._call(
            server, state="YY", county="Sample District", parcel_id="0000-TEST-01"
        )

        self.assertEqual(result["status"], "succeeded")

    async def test_a_state_may_be_named_or_coded(self) -> None:
        source = _FakeTaxSource(county="Sample District", state="DC")
        server = self._server(source)

        result = await self._call(
            server, state="District of Columbia", county="Sample District", parcel_id="1"
        )
        unreadable = await self._call(server, state="Columbia", county="X", parcel_id="1")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(unreadable["status"], "requires_configuration")
        self.assertIn("two-letter code", unreadable["warnings"][0])

    async def test_a_county_without_a_tax_connector_needs_configuration(self) -> None:
        result = await self._call(
            self._server(), state="XX", county="Other", parcel_id="0000-TEST-01"
        )

        self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("Other County, XX", result["warnings"][0])

    async def test_a_blank_parcel_needs_configuration_not_an_error(self) -> None:
        result = await self._call(
            self._server(_FakeTaxSource()), state="XX", county="Sample", parcel_id=" "
        )

        self.assertEqual(result["status"], "requires_configuration")


if __name__ == "__main__":
    unittest.main()

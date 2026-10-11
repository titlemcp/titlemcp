from __future__ import annotations

import json
import unittest
from datetime import date

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.municipal import MunicipalOffice
from title_mcp.mcp.server import create_mcp_server
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import (
    MunicipalDirectory,
    SourceDescriptor,
    SourceKind,
    SourceResult,
    SourceResultStatus,
    municipal_directory_result,
)
from title_mcp.state.memory import InMemoryWorkflowRepository

TODAY = date(2026, 10, 12)
DESCRIPTOR = SourceDescriptor(
    source_id="fake-sample-directory",
    name="Sample State municipal directory",
    kind=SourceKind.MUNICIPAL,
    jurisdiction_scope=JurisdictionScope(country="US", state="XX"),
)


def _office(name: str, kind: str, checked_on: str = "2026-10-11") -> MunicipalOffice:
    return MunicipalOffice.model_validate(
        {
            "name": name,
            "kind": kind,
            "state": "XX",
            "county": "Sample County",
            "checked_on": checked_on,
            "lien_letter": {
                "offered": "yes",
                "channel": "online_portal",
                "request_url": f"https://{name.lower().replace(' ', '')}.example/liens",
                "fee_per_parcel": "60.00",
            },
        }
    )


CITY = _office("Sample City", "municipality")
COUNTY = _office("Sample County", "county")


class RecordTests(unittest.TestCase):
    def _result(self, jurisdiction, municipality, county) -> SourceResult:
        return municipal_directory_result(
            descriptor=DESCRIPTOR,
            jurisdiction=jurisdiction,
            municipality=municipality,
            county=county,
            coverage="Sample State's counties and its larger cities",
            today=TODAY,
        )

    def test_a_city_and_its_county_become_one_record_marked_for_review(self) -> None:
        jurisdiction = Jurisdiction(state="XX", county="Sample County", municipality="Sample City")

        result = self._result(jurisdiction, CITY, COUNTY)

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.municipal_lien_directory")
        self.assertEqual(record["record_type"], "municipal_lien_directory")
        self.assertEqual(record["municipality"]["lien_letter"]["fee_per_parcel"], "60.00")
        self.assertEqual(record["county"]["name"], "Sample County")
        self.assertEqual(record["source"]["checked_on"], "2026-10-11")
        self.assertEqual(
            [citation.uri for citation in result.citations],
            ["https://samplecity.example/liens", "https://samplecounty.example/liens"],
        )
        self.assertEqual(result.citations[0].retrieved_at, "2026-10-11")

    def test_a_city_missing_from_the_directory_is_partial_and_says_what_is_covered(
        self,
    ) -> None:
        jurisdiction = Jurisdiction(state="XX", county="Sample County", municipality="Tiny")

        result = self._result(jurisdiction, None, COUNTY)

        self.assertIs(result.status, SourceResultStatus.PARTIAL)
        self.assertIn("no entry for Tiny", result.warnings[0])
        self.assertIn("Sample State's counties and its larger cities", result.warnings[0])

    def test_a_county_alone_asks_for_the_city_when_there_is_one(self) -> None:
        result = self._result(Jurisdiction(state="XX", county="Sample County"), None, COUNTY)

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertIn("give the municipality", " ".join(result.warnings))

    def test_every_answer_warns_that_the_postal_city_may_differ(self) -> None:
        result = self._result(Jurisdiction(state="XX", county="Sample County"), None, COUNTY)

        self.assertIn("postal city", " ".join(result.warnings))

    def test_an_old_entry_is_called_out(self) -> None:
        old = _office("Sample County", "county", checked_on="2025-06-30")

        result = self._result(Jurisdiction(state="XX", county="Sample County"), None, old)

        self.assertIn("read on 2025-06-30", " ".join(result.warnings))

    def test_nothing_found_is_no_results(self) -> None:
        result = self._result(Jurisdiction(state="XX", county="Other County"), None, None)

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)
        self.assertIsNone(result.records[0]["source"]["checked_on"])


class _FakeDirectory:
    def __init__(self, state: str = "XX") -> None:
        self.source_id = "fake-directory"
        self.descriptor = SourceDescriptor(
            source_id=self.source_id,
            name="Fake directory",
            kind=SourceKind.MUNICIPAL,
            jurisdiction_scope=JurisdictionScope(country="US", state=state),
        )
        self.asked: list[Jurisdiction] = []

    def supports(self, jurisdiction, kind=None) -> bool:
        return (kind is None or kind == SourceKind.MUNICIPAL) and (
            self.descriptor.jurisdiction_scope.matches(jurisdiction)
        )

    async def query(self, query):  # pragma: no cover - not used by the directory tool
        raise NotImplementedError

    async def find_offices(self, jurisdiction) -> SourceResult:
        self.asked.append(jurisdiction)
        return SourceResult(source_id=self.source_id, status=SourceResultStatus.SUCCEEDED)


class MunicipalDirectoryToolTests(unittest.IsolatedAsyncioTestCase):
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
        result = await server.call_tool("municipal_lien_directory", arguments)
        return json.loads(result.content[0].text)

    def test_a_directory_connector_is_recognized(self) -> None:
        self.assertIsInstance(_FakeDirectory(), MunicipalDirectory)

    async def test_the_county_and_city_reach_the_directory(self) -> None:
        directory = _FakeDirectory()
        server = self._server(directory)

        result = await self._call(
            server, state="XX", county="Sample", municipality="  Sample   City "
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(directory.asked[0].county, "Sample County")
        self.assertEqual(directory.asked[0].municipality, "Sample City")

    async def test_the_city_is_optional(self) -> None:
        directory = _FakeDirectory()

        await self._call(self._server(directory), state="XX", county="Sample County")

        self.assertIsNone(directory.asked[0].municipality)

    async def test_a_state_without_a_directory_needs_configuration(self) -> None:
        result = await self._call(self._server(_FakeDirectory()), state="YY", county="Other")

        self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("Other County, YY", result["warnings"][0])

    async def test_a_state_that_is_not_a_state_needs_configuration(self) -> None:
        result = await self._call(self._server(), state="Columbia", county="Sample")

        self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("two-letter code", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()

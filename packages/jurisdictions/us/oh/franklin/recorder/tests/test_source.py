"""The connector contract: what it returns, and what it refuses to guess."""

from __future__ import annotations

import json
import pathlib
import unittest

from titlemcp_us_oh_franklin_recorder.client import (
    RecorderProtocolError,
    RecorderSearchQuery,
    RecorderSearchResult,
    _to_result,
)
from titlemcp_us_oh_franklin_recorder.sources import FranklinRecorderSourceConnector

from title_mcp.domain.models import Jurisdiction
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "name_search.json"
FRANKLIN = Jurisdiction(country="US", state="OH", county="Franklin County")


class FakeRecorderClient:
    """Answers from the fixture. No network in the default suite."""

    def __init__(self, result: RecorderSearchResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.queries: list[RecorderSearchQuery] = []

    async def search(self, query: RecorderSearchQuery) -> RecorderSearchResult:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._result or RecorderSearchResult()


def from_fixture() -> RecorderSearchResult:
    return _to_result(json.loads(FIXTURE.read_text()))


def ask(**criteria: object) -> SourceQuery:
    return SourceQuery(
        jurisdiction=FRANKLIN,
        kind=SourceKind.COUNTY_RECORDER,
        criteria=criteria,
        requested_by="tests",
    )


class QueryNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_search_term_is_upper_cased_for_the_index(self) -> None:
        client = FakeRecorderClient(from_fixture())
        source = FranklinRecorderSourceConnector(client=client)

        await source.query(ask(party_name="Zwink Robert V", parcel_id="030-000526-00"))

        self.assertEqual(client.queries[0].search_value, "ZWINK ROBERT V")

    async def test_an_address_is_not_a_search_term(self) -> None:
        """The county indexes by party and legal description, not by street.

        Refusing without a party name is the honest answer; searching an
        address returns whatever the digits happen to match, which on a real
        query was a 1946 deed matched on a volume number.
        """
        source = FranklinRecorderSourceConnector(client=FakeRecorderClient(from_fixture()))

        result = await source.query(ask(property_address="1150 Glenn Ave"))

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertTrue(any("party_name" in w for w in result.warnings))


class ResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_parcel_scopes_the_answer_to_a_chain(self) -> None:
        source = FranklinRecorderSourceConnector(client=FakeRecorderClient(from_fixture()))

        result = await source.query(ask(party_name="ZWINK ROBERT V", parcel_id="030-000526-00"))

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(len(result.records), 1)
        chain = result.records[0]
        self.assertEqual(chain["parcel_id"], "030-000526-00")
        self.assertEqual(len(chain["open_liens"]), 1)
        self.assertEqual(chain["open_liens"][0]["lenders"], ["BETTER MORTGAGE CORP"])

    async def test_without_a_parcel_the_breadth_is_reported_not_hidden(self) -> None:
        source = FranklinRecorderSourceConnector(client=FakeRecorderClient(from_fixture()))

        result = await source.query(ask(party_name="ZWINK ROBERT V"))

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertGreater(len(result.records), 1)
        self.assertTrue(any("parcel_id" in w for w in result.warnings))

    async def test_an_open_lien_always_asks_for_review(self) -> None:
        source = FranklinRecorderSourceConnector(client=FakeRecorderClient(from_fixture()))

        result = await source.query(ask(party_name="ZWINK ROBERT V", parcel_id="030-000526-00"))

        self.assertTrue(result.requires_human_review)

    async def test_no_documents_is_no_results_rather_than_an_empty_chain(self) -> None:
        source = FranklinRecorderSourceConnector(client=FakeRecorderClient(RecorderSearchResult()))

        result = await source.query(ask(party_name="NOBODY AT ALL", parcel_id="030-000526-00"))

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_protocol_error_fails_the_source_rather_than_raising(self) -> None:
        """A connector that raises takes the workflow down with it."""
        client = FakeRecorderClient(error=RecorderProtocolError("REJECTED: bad query"))
        source = FranklinRecorderSourceConnector(client=client)

        result = await source.query(ask(party_name="ZWINK ROBERT V", parcel_id="030-000526-00"))

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertTrue(result.warnings)

    async def test_an_unreachable_county_fails_the_same_way(self) -> None:
        source = FranklinRecorderSourceConnector(
            client=FakeRecorderClient(error=TimeoutError("no answer"))
        )

        result = await source.query(ask(party_name="ZWINK ROBERT V", parcel_id="030-000526-00"))

        self.assertIs(result.status, SourceResultStatus.FAILED)


class ParsingTests(unittest.TestCase):
    def test_search_highlighting_is_stripped_from_values(self) -> None:
        """The index returns matched terms wrapped in ``<em>``."""
        result = _to_result(json.loads(FIXTURE.read_text()))

        for document in result.documents:
            for name in document.grantors + document.grantees:
                self.assertNotIn("<em>", name)
            self.assertNotIn("<em>", document.volume)


if __name__ == "__main__":
    unittest.main()

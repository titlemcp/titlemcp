from __future__ import annotations

import json
import pathlib
import unittest
from datetime import date
from unittest import mock

from titlemcp_platform_publicsearch import (
    PublicSearchClient,
    PublicSearchProtocolError,
    PublicSearchQuery,
    PublicSearchRecorderConnector,
    PublicSearchResult,
    PublicSearchSiteConfig,
)
from titlemcp_platform_publicsearch.client import SESSION_SECONDS
from titlemcp_platform_publicsearch.index import PublicSearchIndex

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import InstrumentKind, MortgageReleaseQuery
from title_mcp.sources import MortgageReleaseSource, SourceKind, SourceQuery, SourceResultStatus

FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "documents.json").read_text())
CONFIG = PublicSearchSiteConfig(
    source_id="us-xx-example-recorder",
    county="Example County",
    state="xx",
    name="Example County Recorder",
    base_url="https://example.xx.publicsearch.us/",
)
EXAMPLE = Jurisdiction(state="XX", county="Example County")


def _client() -> PublicSearchClient:
    return PublicSearchClient(CONFIG.base_url)


class FakeClient:
    """Answers each search from the fixture whose instrument the search names."""

    def __init__(self, error: Exception | None = None) -> None:
        self._parser = _client()
        self._error = error
        self.queries: list[PublicSearchQuery] = []

    async def search(self, query: PublicSearchQuery, *, excerpt_for: str | None = None):
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        payloads = [
            FIXTURES[name] for name in ("mortgage_lookup", "release_lookup", "stark_style_release")
        ]
        # The document itself first, then anything that mentions the term, as the site does.
        for matches in (
            lambda row: row.get("instrumentNumber") == query.search_value,
            lambda row: query.search_value in json.dumps(row),
        ):
            for payload in payloads:
                if any(matches(row) for row in payload["data"]["byHash"].values()):
                    return self._parser.to_result(payload, excerpt_for=excerpt_for)
        return PublicSearchResult()


class QueryTests(unittest.TestCase):
    def test_the_term_is_upper_cased_for_the_index(self) -> None:
        self.assertEqual(PublicSearchQuery(search_value="Jane Doe").search_value, "JANE DOE")

    def test_dates_become_the_sites_range(self) -> None:
        query = PublicSearchQuery(search_value="X", recorded_from=date(2026, 5, 1))

        self.assertEqual(query.as_payload()["query"]["recordedDateRange"], "20260501,29991231")
        self.assertEqual(
            PublicSearchQuery(search_value="X").recorded_date_range, "16000101,29991231"
        )

    def test_image_text_is_searched_only_when_asked(self) -> None:
        query = PublicSearchQuery(search_value="X", search_ocr_text=True)

        self.assertTrue(query.as_payload()["query"]["searchOcrText"])


class MappingTests(unittest.TestCase):
    def test_a_cuyahoga_style_mortgage_maps_to_a_recorded_instrument(self) -> None:
        [mortgage] = _client().to_result(FIXTURES["mortgage_lookup"]).documents

        self.assertEqual(mortgage.instrument_number, "201904150101")
        self.assertEqual(mortgage.recorded_on, date(2019, 4, 15))
        self.assertIs(mortgage.kind, InstrumentKind.MORTGAGE)
        self.assertEqual(mortgage.document_type_code, "MORT")
        # Search highlighting is stripped from names.
        self.assertEqual(mortgage.grantors[0], "SAMPLETON JANE Q")
        self.assertEqual(mortgage.book, "")
        self.assertIn("EXAMPLE ACRES SUBD", mortgage.legal_description)
        self.assertEqual(mortgage.detail_url, "https://example.xx.publicsearch.us/doc/900000101")
        self.assertEqual(
            [(r.instrument_number, r.kind) for r in mortgage.references],
            [
                ("202101050202", InstrumentKind.ASSIGNMENT),
                ("202605180303", InstrumentKind.RELEASE),
            ],
        )

    def test_image_text_and_signed_links_are_not_passed_on(self) -> None:
        [mortgage] = _client().to_result(FIXTURES["mortgage_lookup"]).documents

        for field in ("ocrText", "thumbnail", "images", "downloadLink"):
            self.assertNotIn(field, mortgage.raw)
        self.assertEqual(mortgage.text_excerpt, "")

    def test_a_stark_style_release_reads_the_same(self) -> None:
        documents = _client().to_result(FIXTURES["stark_style_release"]).documents
        by_number = {d.instrument_number: d for d in documents}

        release = by_number["202606020000404"]
        self.assertIs(release.kind, InstrumentKind.RELEASE)
        self.assertEqual((release.book, release.page), ("1234", "56"))
        self.assertEqual(release.legal_description, "LOT 7 EXAMPLE ALLOTMENT")
        self.assertIs(release.references[0].kind, InstrumentKind.MORTGAGE)
        self.assertIs(by_number["202606020000606"].kind, InstrumentKind.MODIFICATION)

    def test_an_excerpt_is_kept_around_the_number_searched_for(self) -> None:
        documents = (
            _client()
            .to_result(FIXTURES["stark_style_release"], excerpt_for="201508080000505")
            .documents
        )
        release = next(d for d in documents if d.instrument_number == "202606020000404")

        self.assertIn("Instrument No. 201508080000505", release.text_excerpt)
        self.assertLess(len(release.text_excerpt), 200)

    def test_a_county_can_correct_the_classifier_by_type_code(self) -> None:
        client = PublicSearchClient(
            CONFIG.base_url, document_type_kinds={"MD/M": InstrumentKind.OTHER}
        )
        documents = client.to_result(FIXTURES["stark_style_release"]).documents

        modification = next(d for d in documents if d.document_type_code == "MD/M")
        self.assertIs(modification.kind, InstrumentKind.OTHER)


class _Socket:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = [json.dumps(reply) for reply in replies]
        self.sent: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        reply = json.loads(self.replies.pop(0))
        if reply.get("correlationId") == "SENT":
            reply["correlationId"] = self.sent[-1]["correlationId"]
        return json.dumps(reply)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, replies: list[list[dict]], clock=None) -> tuple[PublicSearchClient, list]:
        sessions: list[int] = []
        sockets = [_Socket(r) for r in replies]

        async def open_session():
            sessions.append(1)
            return "token-1", "authToken=token-1"

        def connect(url, **kwargs):
            return sockets.pop(0)

        client = PublicSearchClient(
            CONFIG.base_url,
            session_factory=open_session,
            connect_factory=connect,
            clock=clock or (lambda: 0.0),
        )
        return client, sessions

    async def test_replies_are_matched_on_the_id_sent_and_the_session_is_reused(self) -> None:
        fulfilled = {
            "type": "@kofile/FETCH_DOCUMENTS_FULFILLED/v6",
            "correlationId": "SENT",
            "payload": FIXTURES["release_lookup"],
        }
        unrelated = {"type": "@kofile/SOMETHING_ELSE", "correlationId": "other"}
        client, sessions = self._client([[unrelated, fulfilled], [fulfilled]])

        first = await client.search(PublicSearchQuery(search_value="202605180303"))
        await client.search(PublicSearchQuery(search_value="202605180303"))

        self.assertEqual(first.documents[0].instrument_number, "202605180303")
        self.assertEqual(len(sessions), 1)

    async def test_a_stale_session_is_replaced(self) -> None:
        fulfilled = {
            "type": "FETCH_DOCUMENTS_FULFILLED",
            "correlationId": "SENT",
            "payload": {},
        }
        now = [0.0]
        client, sessions = self._client([[fulfilled], [fulfilled]], clock=lambda: now[0])

        await client.search(PublicSearchQuery(search_value="X"))
        now[0] = SESSION_SECONDS + 1
        await client.search(PublicSearchQuery(search_value="X"))

        self.assertEqual(len(sessions), 2)

    async def test_a_refusal_raises_and_drops_the_session(self) -> None:
        rejected = {"type": "FETCH_DOCUMENTS_REJECTED", "correlationId": "SENT", "payload": "no"}
        fulfilled = {"type": "FETCH_DOCUMENTS_FULFILLED", "correlationId": "SENT", "payload": {}}
        client, sessions = self._client([[rejected], [fulfilled]])

        with self.assertRaises(PublicSearchProtocolError):
            await client.search(PublicSearchQuery(search_value="X"))
        await client.search(PublicSearchQuery(search_value="X"))

        self.assertEqual(len(sessions), 2)

    async def test_searches_are_spaced_out(self) -> None:
        fulfilled = {"type": "FETCH_DOCUMENTS_FULFILLED", "correlationId": "SENT", "payload": {}}
        client, _ = self._client([[fulfilled], [fulfilled]])
        client.min_interval_seconds = 0.5

        with mock.patch("asyncio.sleep") as sleep:
            await client.search(PublicSearchQuery(search_value="X"))
            await client.search(PublicSearchQuery(search_value="X"))

        sleep.assert_called_once_with(0.5)


class IndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_document_already_seen_is_not_searched_again(self) -> None:
        client = FakeClient()
        index = PublicSearchIndex(client)

        await index.by_instrument("201904150101")
        await index.by_instrument("201904150101")

        self.assertEqual(len(client.queries), 1)

    async def test_a_party_search_cleans_the_name_first(self) -> None:
        client = FakeClient()

        await PublicSearchIndex(client).by_party("Jane Q. Sampleton, a widow")

        self.assertEqual(client.queries[0].search_value, "JANE SAMPLETON")

    async def test_citing_searches_image_text_and_keeps_only_documents_that_cite(self) -> None:
        client = FakeClient()

        found = await PublicSearchIndex(client).citing("201508080000505")

        self.assertTrue(client.queries[0].search_ocr_text)
        self.assertEqual([d.instrument_number for d in found], ["202606020000404"])


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def _ask(self, **criteria) -> SourceQuery:
        return SourceQuery(jurisdiction=EXAMPLE, kind=SourceKind.COUNTY_RECORDER, criteria=criteria)

    def test_it_is_a_release_source_for_its_county_only(self) -> None:
        connector = PublicSearchRecorderConnector(CONFIG, client=FakeClient())

        self.assertIsInstance(connector, MortgageReleaseSource)
        self.assertTrue(connector.supports(EXAMPLE, SourceKind.COUNTY_RECORDER))
        self.assertFalse(connector.supports(Jurisdiction(state="XX", county="Other County")))
        self.assertEqual(connector.descriptor.base_url, "https://example.xx.publicsearch.us")

    async def test_a_search_needs_a_party_or_an_instrument(self) -> None:
        connector = PublicSearchRecorderConnector(CONFIG, client=FakeClient())

        result = await connector.query(self._ask(property_address="1 Example St"))

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertIn("not by street address", result.warnings[0])

    async def test_a_search_returns_instruments_with_citations(self) -> None:
        connector = PublicSearchRecorderConnector(CONFIG, client=FakeClient())

        result = await connector.query(self._ask(instrument_number="201904150101"))

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        self.assertEqual(result.records[0]["kind"], "mortgage")
        self.assertEqual(result.citations[0].recording_reference, "201904150101")

    async def test_the_county_failing_is_a_failed_result_not_an_exception(self) -> None:
        connector = PublicSearchRecorderConnector(
            CONFIG, client=FakeClient(error=PublicSearchProtocolError("REJECTED: busy"))
        )

        result = await connector.find_release(
            EXAMPLE, MortgageReleaseQuery(mortgage_instrument_number="201904150101")
        )

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("REJECTED: busy", result.warnings[0])

    async def test_a_release_the_county_links_to_the_mortgage_is_found(self) -> None:
        connector = PublicSearchRecorderConnector(CONFIG, client=FakeClient())

        result = await connector.find_release(
            EXAMPLE,
            MortgageReleaseQuery(
                mortgage_instrument_number="201904150101", paid_off_on="2026-05-01"
            ),
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.mortgage_release_search")
        self.assertEqual(record["status"], "released")
        self.assertEqual(record["mortgage_identified_by"], "instrument_number")
        [match] = record["releases"]
        self.assertEqual(match["basis"], "index_reference")
        self.assertEqual(match["release"]["instrument_number"], "202605180303")
        self.assertEqual(match["release"]["recorded_on"], "2026-05-18")


if __name__ == "__main__":
    unittest.main()

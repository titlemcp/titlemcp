from __future__ import annotations

import json
import pathlib
import unittest
from datetime import date

from titlemcp_platform_countyfusion import (
    CountyFusionClient,
    CountyFusionProtocolError,
    CountyFusionRecorderConnector,
    CountyFusionSiteConfig,
)
from titlemcp_platform_countyfusion.index import CountyFusionIndex, surname_first

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import InstrumentKind, MortgageReleaseQuery
from title_mcp.sources import MortgageReleaseSource, SourceKind, SourceQuery, SourceResultStatus

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONFIG = CountyFusionSiteConfig(
    source_id="us-xx-example-recorder",
    county="Example County",
    state="xx",
    name="Example County Recorder",
    host="https://countyfusion0.example.test/",
    county_key="ExampleXX",
    min_interval_seconds=0,
)
EXAMPLE = Jurisdiction(state="XX", county="Example County")


class _Answer:
    def __init__(self, status: int = 200, text: str = "", location: str = "") -> None:
        self.status_code = status
        self.text = text
        self.headers = {"Location": location} if location else {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


class _FakeSite:
    """A CountyFusion site answering from the fixtures, recording every request."""

    def __init__(self, *, lapse_first_search: bool = False) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.logins = 0
        self._lapse = lapse_first_search

    def session(self):
        return self

    def request(self, method, url, **kwargs):
        path = url.split("/countyweb", 1)[1]
        self.requests.append((method, path, kwargs.get("data") or kwargs.get("params") or {}))
        if path.startswith("/loginDisplay.action"):
            self.logins += 1
            return _Answer(text='<input type="hidden" name="token" value="tok-1">')
        if path == "/login.action":
            return _Answer(302, location="/countyweb/main.jsp")
        if path == "/disclaimer.do":
            return _Answer(text="search/searchMain.do")
        if path.startswith("/search/searchExecute.do"):
            if self._lapse:
                self._lapse = False
                return _Answer(text="<form action='loginDisplay.action'>")
            if "NOBODY" in kwargs["data"].get("ALLNAMES", ""):
                return _Answer(text=(FIXTURES / "nothing_found.html").read_text())
            return _Answer(302, location="searchResults.do?searchSessionId=searchJobMain")
        if path.startswith("/search/searchResults.do"):
            return _Answer(
                302,
                location=(
                    "SearchResultsView.jsp?navStateDisplay=Displaying+1-2+of+2+Items"
                    "&startCursor=0&curSortColumn=RecordDate"
                ),
            )
        if path.endswith("docs_SearchResultList.jsp"):
            return _Answer(text=(FIXTURES / "result_list.html").read_text())
        if path == "/search/getSearchResultsDetails.do":
            return _Answer(text=(FIXTURES / "mortgage_detail.json").read_text())
        return _Answer(404)

    def paths(self) -> list[str]:
        return [path.split("?")[0] for _, path, _ in self.requests]


def _client(site: _FakeSite, **kwargs) -> CountyFusionClient:
    return CountyFusionClient(CONFIG, session_factory=site.session, **kwargs)


class MappingTests(unittest.TestCase):
    def test_result_rows_put_each_party_on_its_side(self) -> None:
        mortgage, release = _client(_FakeSite()).rows((FIXTURES / "result_list.html").read_text())

        self.assertEqual(mortgage.instrument_number, "201904150101")
        self.assertIs(mortgage.kind, InstrumentKind.MORTGAGE)
        self.assertEqual(mortgage.recorded_on, date(2019, 4, 15))
        self.assertEqual((mortgage.book, mortgage.page), ("912", "3344"))
        # The full party list is in the span's title, not its text.
        self.assertEqual(mortgage.grantors, ["SAMPLETON JANE Q", "SAMPLETON JOHN R"])
        self.assertEqual(mortgage.grantees, ["EXAMPLE SAVINGS BANK"])
        self.assertEqual(mortgage.raw, {"inst_id": "7000101", "has_links": True})
        self.assertIs(release.kind, InstrumentKind.RELEASE)
        # The list only flags links; their contents come from the detail.
        self.assertEqual(release.references, [])

    def test_a_detail_lists_the_documents_linked_to_it(self) -> None:
        payload = json.loads((FIXTURES / "mortgage_detail.json").read_text())

        mortgage = _client(_FakeSite()).document(payload, "7000101")

        self.assertEqual(mortgage.recorded_on, date(2019, 4, 15))
        self.assertEqual((mortgage.book, mortgage.page), ("912", "3344"))
        self.assertEqual(mortgage.legal_description, "SDIV: EXAMPLE ACRES | Lot 12")
        self.assertEqual(
            [(r.instrument_number, r.kind) for r in mortgage.references],
            [
                ("202605180303", InstrumentKind.RELEASE),
                ("202101050202", InstrumentKind.ASSIGNMENT),
            ],
        )

    def test_a_link_says_enough_about_the_document_to_skip_fetching_it(self) -> None:
        client = _client(_FakeSite())
        payload = json.loads((FIXTURES / "mortgage_detail.json").read_text())
        linked = client.document(payload, "7000101").raw["linked"][0]

        release = client.linked_stub(linked)

        self.assertEqual(release.instrument_number, "202605180303")
        self.assertEqual(release.recorded_on, date(2026, 5, 18))
        self.assertEqual((release.book, release.page), ("1007", "1946"))
        self.assertEqual(release.raw["inst_id"], "7000303")

    def test_a_county_can_correct_the_classifier(self) -> None:
        # One county's plain "RELEASE" releases a lease, not a mortgage.
        config = CONFIG.model_copy(
            update={"document_type_kinds": {"RELEASE": InstrumentKind.OTHER}}
        )
        client = CountyFusionClient(config, session_factory=_FakeSite().session)

        self.assertIs(client._kind("Release"), InstrumentKind.OTHER)
        self.assertIs(client._kind("MORTGAGE RELEASE"), InstrumentKind.RELEASE)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_public_login_serves_many_searches(self) -> None:
        site = _FakeSite()
        client = _client(site)

        await client.search_instrument("201904150101")
        await client.search_instrument("202605180303")

        self.assertEqual(site.logins, 1)
        self.assertEqual(
            site.paths()[:3], ["/loginDisplay.action", "/login.action", "/disclaimer.do"]
        )
        login_form = site.requests[1][2]
        self.assertEqual((login_form["public"], login_form["token"]), ("true", "tok-1"))

    async def test_a_search_that_finds_nothing_is_empty_not_an_error(self) -> None:
        site = _FakeSite()

        found = await _client(site).search_names("NOBODY SAMPLE")

        self.assertEqual(found, [])
        self.assertEqual(site.logins, 1)

    async def test_a_lapsed_session_is_replaced_once(self) -> None:
        site = _FakeSite(lapse_first_search=True)

        found = await _client(site).search_instrument("201904150101")

        self.assertEqual(len(found), 2)
        self.assertEqual(site.logins, 2)

    async def test_a_detail_first_runs_a_search_to_open_the_session(self) -> None:
        site = _FakeSite()

        mortgage = await _client(site).detail("7000101")

        self.assertEqual(mortgage.instrument_number, "201904150101")
        executes = [p for p in site.paths() if p.startswith("/search/searchExecute.do")]
        self.assertEqual(len(executes), 1)
        self.assertEqual(site.paths()[-1], "/search/getSearchResultsDetails.do")

    async def test_requests_are_spaced_out(self) -> None:
        slept: list[float] = []
        config = CONFIG.model_copy(update={"min_interval_seconds": 1.1})
        client = CountyFusionClient(
            config, session_factory=_FakeSite().session, clock=lambda: 0.0, sleep=slept.append
        )

        await client.search_instrument("201904150101")

        self.assertTrue(slept)
        self.assertTrue(all(wait == 1.1 for wait in slept))

    async def test_a_dates_search_sends_the_sites_format(self) -> None:
        site = _FakeSite()

        await _client(site).search_names("SAMPLETON JANE", recorded_from=date(2026, 5, 1))

        form = next(data for _, path, data in site.requests if "searchExecute" in path)
        self.assertEqual(form["FROMDATE"], "05/01/2026")
        self.assertEqual(form["ALLNAMES"], "SAMPLETON JANE")


class IndexTests(unittest.IsolatedAsyncioTestCase):
    def test_people_are_searched_surname_first_and_businesses_as_written(self) -> None:
        self.assertEqual(surname_first("JANE Q SAMPLETON"), "SAMPLETON JANE Q")
        self.assertEqual(surname_first("EXAMPLE HOMES LLC"), "EXAMPLE HOMES LLC")
        self.assertEqual(surname_first("SAMPLETON"), "SAMPLETON")

    async def test_a_name_finding_nothing_is_tried_as_written(self) -> None:
        site = _FakeSite()

        await CountyFusionIndex(_client(site)).by_party("Nobody Sample")

        names = [data["ALLNAMES"] for _, path, data in site.requests if "searchExecute" in path]
        self.assertEqual(names, ["SAMPLE NOBODY", "NOBODY SAMPLE"])

    async def test_links_are_read_once_and_followed_without_another_request(self) -> None:
        site = _FakeSite()
        index = CountyFusionIndex(_client(site))
        [mortgage] = await index.by_instrument("201904150101")

        linked = await index.with_links(mortgage)
        before = len(site.requests)
        [release] = await index.by_instrument("202605180303")

        self.assertEqual(linked.references[0].instrument_number, "202605180303")
        self.assertEqual(release.recorded_on, date(2026, 5, 18))
        self.assertEqual(len(site.requests), before)


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def _connector(self, site: _FakeSite | None = None) -> CountyFusionRecorderConnector:
        return CountyFusionRecorderConnector(CONFIG, client=_client(site or _FakeSite()))

    def test_it_is_a_release_source_for_its_county(self) -> None:
        connector = self._connector()

        self.assertIsInstance(connector, MortgageReleaseSource)
        self.assertTrue(connector.supports(EXAMPLE, SourceKind.COUNTY_RECORDER))
        self.assertEqual(
            connector.descriptor.base_url, "https://countyfusion0.example.test/countyweb"
        )

    async def test_a_search_needs_a_party_or_an_instrument(self) -> None:
        result = await self._connector().query(
            SourceQuery(jurisdiction=EXAMPLE, kind=SourceKind.COUNTY_RECORDER, criteria={})
        )

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)

    async def test_the_site_failing_is_a_failed_result(self) -> None:
        class _Refusing(_FakeSite):
            def request(self, method, url, **kwargs):
                raise CountyFusionProtocolError("The public login was refused.")

        result = await self._connector(_Refusing()).find_release(
            EXAMPLE, MortgageReleaseQuery(mortgage_instrument_number="201904150101")
        )

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("refused", result.warnings[0])

    async def test_a_release_the_county_links_to_the_mortgage_is_found(self) -> None:
        result = await self._connector().find_release(
            EXAMPLE,
            MortgageReleaseQuery(
                mortgage_instrument_number="201904150101", paid_off_on="2026-05-01"
            ),
        )

        [record] = result.records
        self.assertEqual(record["status"], "released")
        [match] = record["releases"]
        self.assertEqual(match["basis"], "index_reference")
        self.assertEqual(match["release"]["instrument_number"], "202605180303")
        self.assertEqual(match["release"]["recorded_on"], "2026-05-18")


if __name__ == "__main__":
    unittest.main()

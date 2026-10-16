from __future__ import annotations

import copy
import json
import pathlib
import unittest
from datetime import date

from requests import ConnectionError as RequestsConnectionError
from titlemcp_platform_fidlarava import (
    FidlarAvaCaptchaRequired,
    FidlarAvaClient,
    FidlarAvaProtocolError,
    FidlarAvaRecorderConnector,
    FidlarAvaSiteConfig,
    build_recorder_source_connector,
)
from titlemcp_platform_fidlarava.client import CRITERIA_FIELDS
from titlemcp_platform_fidlarava.index import FidlarAvaIndex, party_terms

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import InstrumentKind, MortgageReleaseQuery
from title_mcp.sources import MortgageReleaseSource, SourceKind, SourceQuery, SourceResultStatus

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
APP = "https://ava.example.test/XXExample/AvaWeb/"
API = "https://ava.example.test/XXExample/Scrap.WebService.Ava/"
CONFIG = FidlarAvaSiteConfig(
    source_id="us-xx-example-recorder",
    county="Example County",
    state="xx",
    name="Example County Recorder",
    app_url=APP.rstrip("/"),
    min_interval_seconds=0,
)
EXAMPLE = Jurisdiction(state="XX", county="Example County")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class _Answer:
    def __init__(self, status: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self.content = (json.dumps(payload) if payload is not None else text).encode()


class _FakeSite:
    """An AVA site answering from the fixtures, recording every request.

    Its searches match the way the site's wildcard searches do: a criterion
    matches any value starting with it.
    """

    def __init__(
        self,
        *,
        reject_token_once: int | None = None,
        refuse: _Answer | None = None,
        documents: list[dict] | None = None,
    ) -> None:
        self.requests: list[tuple[str, str, dict, dict]] = []
        self.logins = 0
        self.documents = documents or _fixture("documents.json")["DocResults"]
        # HTTP 401, or a 200 carrying ResultAction 1, for the first search.
        self._reject_token = reject_token_once
        self._refuse = refuse

    def session(self):
        return self

    def request(self, method, url, **kwargs):
        body = kwargs.get("json") if kwargs.get("json") is not None else kwargs.get("data") or {}
        self.requests.append((method, url, body, kwargs.get("headers") or {}))
        if url == APP + "appConfig.json":
            return _Answer(payload=_fixture("app_config.json"))
        if url == API + "breeze/Settings":
            return _Answer(payload=_fixture("settings.json"))
        if url == API + "token":
            self.logins += 1
            token = dict(_fixture("token.json"), access_token=f"example-token-{self.logins}")
            return _Answer(payload=token)
        if url == API + "breeze/Search":
            if self._refuse is not None:
                return self._refuse
            if self._reject_token == 401:
                self._reject_token = None
                return _Answer(401, {"Message": "Authorization has been denied for this request."})
            if self._reject_token == 1:
                self._reject_token = None
                return _Answer(payload={"Success": False, "ResultAction": 1, "Msg": None})
            answer = _fixture("search_answer.json")
            answer["DocResults"] = [row for row in self.documents if _matches(row, body)]
            answer["TotalResults"] = answer["ViewableResults"] = len(answer["DocResults"])
            return _Answer(payload=answer)
        return _Answer(404, text="Not Found")

    def searches(self) -> list[dict]:
        return [body for _, url, body, _ in self.requests if url.endswith("breeze/Search")]

    def urls(self) -> list[str]:
        return [url for _, url, _, _ in self.requests]


def _matches(row: dict, criteria: dict) -> bool:
    def starts(value, wanted: str) -> bool:
        return str(value or "").upper().startswith(wanted.upper())

    if criteria["DocumentName"] and not starts(row["DocumentName"], criteria["DocumentName"]):
        return False
    if criteria["Book"] and not starts(row["Book"], criteria["Book"]):
        return False
    if criteria["Page"] and not starts(row["Page"], criteria["Page"]):
        return False
    if criteria["LastBusinessName"]:
        names = [party["Name"].split() for party in row["Parties"]]
        if not any(
            starts(words[0], criteria["LastBusinessName"].split()[0])
            and (not criteria["FirstName"] or criteria["FirstName"] in words[1:])
            for words in names
        ):
            return False
    return True


def _client(site: _FakeSite, config: FidlarAvaSiteConfig = CONFIG, **kwargs) -> FidlarAvaClient:
    return FidlarAvaClient(config, session_factory=site.session, **kwargs)


def _row(number: str) -> dict:
    rows = _fixture("documents.json")["DocResults"]
    return copy.deepcopy(next(row for row in rows if row["DocumentName"] == number))


class ConfigTests(unittest.TestCase):
    def test_a_site_is_normalized(self) -> None:
        config = FidlarAvaSiteConfig(
            source_id="us-xx-example-recorder",
            county="Example County",
            state="xx",
            name="Example County Recorder",
            app_url="https://ava.example.test/XXExample/AvaWeb",
            document_type_kinds={" canc ": InstrumentKind.RELEASE},
        )

        self.assertEqual(config.state, "XX")
        self.assertEqual(config.app_url, APP)
        self.assertEqual(config.document_type_kinds, {"CANC": InstrumentKind.RELEASE})
        self.assertEqual(config.min_interval_seconds, 1.1)


class MappingTests(unittest.TestCase):
    def test_a_row_is_a_recorded_instrument(self) -> None:
        mortgage = _client(_FakeSite()).document(_row("2019EX000101"))

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertIs(mortgage.kind, InstrumentKind.MORTGAGE)
        self.assertEqual(mortgage.recorded_on, date(2019, 4, 15))
        self.assertEqual((mortgage.book, mortgage.page), ("912", "3344"))
        self.assertEqual(mortgage.grantors, ["SAMPLETON JANE Q", "SAMPLETON JOHN R"])
        self.assertEqual(mortgage.grantees, ["EXAMPLE SAVINGS BANK"])
        self.assertEqual(mortgage.legal_description, "00-000-0000 EXAMPLE ACRES LOT 12")
        self.assertEqual(mortgage.raw["id"], "7000101")

    def test_associated_documents_are_references_by_number_only(self) -> None:
        mortgage = _client(_FakeSite()).document(_row("2019EX000101"))

        self.assertEqual(
            [(r.instrument_number, r.document_type, r.kind) for r in mortgage.references],
            [
                ("2021EX000202", "", InstrumentKind.OTHER),
                ("2026EX000303", "", InstrumentKind.OTHER),
            ],
        )
        self.assertEqual(
            mortgage.raw["associated"][1],
            {"id": "7000303", "number": "2026EX000303", "image_exists": True},
        )

    def test_a_release_keeps_its_notes_and_its_link_back(self) -> None:
        release = _client(_FakeSite()).document(_row("2026EX000303"))

        self.assertIs(release.kind, InstrumentKind.RELEASE)
        self.assertEqual(release.recorded_on, date(2026, 5, 18))
        self.assertTrue(release.cites("2019EX000101"))
        self.assertEqual(release.raw["notes"], "SAT OF MTG 2019EX000101")

    def test_a_county_can_correct_the_classifier(self) -> None:
        # One county writes "M" for a mortgage and "CANC" for its release.
        config = CONFIG.model_copy(
            update={
                "document_type_kinds": {
                    "M": InstrumentKind.MORTGAGE,
                    "CANC": InstrumentKind.RELEASE,
                }
            }
        )
        client = _client(_FakeSite(), config)
        mortgage, release = _row("2019EX000101"), _row("2026EX000303")
        mortgage["DocumentType"], release["DocumentType"] = "M ", "CANC"

        self.assertIs(client.document(mortgage).kind, InstrumentKind.MORTGAGE)
        self.assertIs(client.document(release).kind, InstrumentKind.RELEASE)
        self.assertIs(client._kind("PT/REL"), InstrumentKind.PARTIAL_RELEASE)

    def test_a_row_with_no_book_or_page_has_empty_ones(self) -> None:
        row = _row("2019EX000101")
        row["Book"] = row["Page"] = None

        mortgage = _client(_FakeSite()).document(row)

        self.assertEqual((mortgage.book, mortgage.page), ("", ""))


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_app_config_names_the_api_and_the_login_is_anonymous(self) -> None:
        site = _FakeSite()

        await _client(site).search_instrument("2019EX000101")

        self.assertEqual(
            site.urls(),
            [
                APP + "appConfig.json",
                API + "breeze/Settings",
                API + "token",
                API + "breeze/Search",
            ],
        )
        login = site.requests[2][2]
        self.assertEqual(
            login, {"grant_type": "password", "username": "anonymous", "password": "anonymous"}
        )
        self.assertEqual(site.requests[1][2], {})

    async def test_a_search_carries_the_token_and_an_empty_captcha(self) -> None:
        site = _FakeSite()
        client = _client(site)

        await client.search_instrument("2019EX000101")

        headers = site.requests[-1][3]
        self.assertEqual(headers["Authorization"], "Bearer example-token-1")
        self.assertEqual(headers["FidlarCaptchaSolution"], "")
        self.assertTrue(client.settings["Search"]["BookPageSearchEnabled"])

    async def test_one_login_serves_many_searches(self) -> None:
        site = _FakeSite()
        client = _client(site)

        await client.search_instrument("2019EX000101")
        await client.search_instrument("2026EX000303")

        self.assertEqual(site.logins, 1)
        self.assertEqual(site.urls().count(APP + "appConfig.json"), 1)

    async def test_a_token_refused_with_http_401_is_replaced_once(self) -> None:
        site = _FakeSite(reject_token_once=401)

        [mortgage] = await _client(site).search_instrument("2019EX000101")

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertEqual(site.logins, 2)
        self.assertEqual(site.requests[-1][3]["Authorization"], "Bearer example-token-2")

    async def test_a_token_refused_with_result_action_1_is_replaced_once(self) -> None:
        site = _FakeSite(reject_token_once=1)

        [mortgage] = await _client(site).search_instrument("2019EX000101")

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertEqual(site.logins, 2)

    async def test_a_token_refused_twice_is_an_error(self) -> None:
        site = _FakeSite(refuse=_Answer(401, {"Message": "Authorization has been denied."}))

        with self.assertRaises(FidlarAvaProtocolError):
            await _client(site).search_instrument("2019EX000101")
        self.assertEqual(site.logins, 2)

    async def test_a_session_that_failed_to_open_is_opened_again(self) -> None:
        class _DownOnce(_FakeSite):
            down = True

            def request(self, method, url, **kwargs):
                if self.down:
                    self.down = False
                    raise RequestsConnectionError("connection refused")
                return super().request(method, url, **kwargs)

        site = _DownOnce()
        client = _client(site)

        with self.assertRaises(RequestsConnectionError):
            await client.search_instrument("2019EX000101")
        [mortgage] = await client.search_instrument("2019EX000101")

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertEqual(site.urls()[0], APP + "appConfig.json")

    async def test_every_criterion_is_sent_and_only_the_searched_ones_are_filled(self) -> None:
        site = _FakeSite()
        client = _client(site)

        await client.search_instrument(" 2019EX000101 ")
        await client.search_book_page("912", "3344")
        await client.search_party("Sampleton", "Jane", recorded_from=date(2026, 5, 1))

        by_number, by_book_page, by_party = site.searches()
        for criteria in (by_number, by_book_page, by_party):
            self.assertEqual(list(criteria), list(CRITERIA_FIELDS))
        self.assertEqual(
            {key: value for key, value in by_number.items() if value},
            {"DocumentName": "2019EX000101"},
        )
        self.assertEqual(
            {key: value for key, value in by_book_page.items() if value},
            {"Book": "912", "Page": "3344"},
        )
        self.assertEqual(
            {key: value for key, value in by_party.items() if value},
            {"LastBusinessName": "SAMPLETON", "FirstName": "JANE", "StartDate": "2026-05-01"},
        )

    async def test_requests_are_spaced_out(self) -> None:
        slept: list[float] = []
        config = CONFIG.model_copy(update={"min_interval_seconds": 10})
        client = FidlarAvaClient(
            config, session_factory=_FakeSite().session, clock=lambda: 0.0, sleep=slept.append
        )

        await client.search_instrument("2019EX000101")

        # Four requests: the first goes at once, each after it waits.
        self.assertEqual(slept, [10, 10, 10])

    async def test_a_search_that_finds_nothing_is_empty(self) -> None:
        found = await _client(_FakeSite()).search_instrument("2099EX999999")

        self.assertEqual(found, [])

    async def test_a_refusal_saying_nothing_matched_is_empty(self) -> None:
        refusal = _Answer(payload={"Success": False, "ResultAction": 6, "Msg": "No results found."})

        found = await _client(_FakeSite(refuse=refusal)).search_instrument("2099EX999999")

        self.assertEqual(found, [])

    async def test_a_site_asking_for_a_captcha_is_reported_not_solved(self) -> None:
        for refusal in (
            _Answer(412, {"Message": "Precondition Failed"}),
            _Answer(
                payload={"Success": False, "ResultAction": 7, "Msg": "A valid captcha is required."}
            ),
        ):
            site = _FakeSite(refuse=refusal)

            with self.assertRaises(FidlarAvaCaptchaRequired) as caught:
                await _client(site).search_instrument("2019EX000101")

            self.assertIn("captcha", str(caught.exception))
            # Asked once, and not asked again with anything in the header.
            self.assertEqual(len(site.searches()), 1)
            self.assertEqual(site.requests[-1][3]["FidlarCaptchaSolution"], "")

    async def test_a_search_the_site_wants_paid_for_is_an_error(self) -> None:
        site = _FakeSite(refuse=_Answer(402, {"Success": False, "ResultAction": 3, "Msg": None}))

        with self.assertRaisesRegex(FidlarAvaProtocolError, "payment"):
            await _client(site).search_instrument("2019EX000101")

    async def test_any_other_refusal_says_what_the_site_said(self) -> None:
        refusal = _Answer(
            payload={"Success": False, "ResultAction": 6, "Msg": "Search is unavailable."}
        )

        with self.assertRaisesRegex(FidlarAvaProtocolError, "Search is unavailable."):
            await _client(_FakeSite(refuse=refusal)).search_instrument("2019EX000101")

    async def test_an_answer_that_is_not_json_is_an_error(self) -> None:
        with self.assertRaises(FidlarAvaProtocolError):
            await _client(_FakeSite(refuse=_Answer(text="<html></html>"))).search_instrument("1")


class IndexTests(unittest.IsolatedAsyncioTestCase):
    def test_people_are_searched_by_surname_and_first_name(self) -> None:
        self.assertEqual(
            party_terms("JANE SAMPLETON"), [("SAMPLETON", "JANE"), ("JANE", "SAMPLETON")]
        )
        self.assertEqual(
            party_terms("JOHN SAMPLETON JR"), [("SAMPLETON", "JOHN"), ("JOHN", "SAMPLETON")]
        )
        self.assertEqual(party_terms("EXAMPLE SAVINGS BANK"), [("EXAMPLE SAVINGS BANK", "")])
        self.assertEqual(party_terms("SAMPLETON"), [("SAMPLETON", "")])
        self.assertEqual(party_terms(""), [])

    async def test_an_instrument_is_found_by_its_number_only(self) -> None:
        site = _FakeSite()
        index = FidlarAvaIndex(_client(site))

        [mortgage] = await index.by_instrument(" 2019EX000101 ")
        again = await index.by_instrument("2019-EX-000101")
        missing = await index.by_instrument("2019EX0001")
        missing_again = await index.by_instrument("2019EX0001")

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertEqual(again, [mortgage])
        # "2019EX0001" starts the mortgage's number, but isn't it.
        self.assertEqual((missing, missing_again), ([], []))
        self.assertEqual(len(site.searches()), 2)

    async def test_a_book_and_page_finds_only_the_document_recorded_there(self) -> None:
        site = _FakeSite()
        index = FidlarAvaIndex(_client(site))

        [mortgage] = await index.by_book_page("912", "3344")
        [same] = await index.by_book_page("0912", " 03344 ")
        elsewhere = await index.by_book_page("912", "3345")

        self.assertEqual(mortgage.instrument_number, "2019EX000101")
        self.assertEqual(same.instrument_number, "2019EX000101")
        self.assertEqual(elsewhere, [])
        # The padded search found nothing as given, and was tried without the zeros.
        self.assertEqual(
            [(s["Book"], s["Page"]) for s in site.searches()],
            [("912", "3344"), ("0912", "03344"), ("912", "3344"), ("912", "3345")],
        )

    async def test_nothing_cites_by_text(self) -> None:
        site = _FakeSite()

        self.assertEqual(await FidlarAvaIndex(_client(site)).citing("2019EX000101"), [])
        self.assertEqual(site.requests, [])

    async def test_a_person_is_searched_by_surname_and_first_name(self) -> None:
        site = _FakeSite()

        found = await FidlarAvaIndex(_client(site)).by_party(
            "Jane Q. Sampleton, a married woman", recorded_from=date(2019, 1, 1)
        )

        self.assertEqual([d.instrument_number for d in found], ["2019EX000101", "2026EX000303"])
        [criteria] = site.searches()
        self.assertEqual(
            (criteria["LastBusinessName"], criteria["FirstName"]), ("SAMPLETON", "JANE")
        )
        self.assertEqual(criteria["StartDate"], "2019-01-01")

    async def test_a_name_given_surname_first_is_found_on_the_second_try(self) -> None:
        site = _FakeSite()

        found = await FidlarAvaIndex(_client(site)).by_party("SAMPLETON JANE")

        self.assertTrue(found)
        self.assertEqual(
            [(s["LastBusinessName"], s["FirstName"]) for s in site.searches()],
            [("JANE", "SAMPLETON"), ("SAMPLETON", "JANE")],
        )

    async def test_a_business_is_searched_by_its_whole_name(self) -> None:
        site = _FakeSite()

        await FidlarAvaIndex(_client(site)).by_party("Example Homes, LLC")

        [criteria] = site.searches()
        self.assertEqual(
            (criteria["LastBusinessName"], criteria["FirstName"]), ("EXAMPLE HOMES LLC", "")
        )

    async def test_links_are_looked_up_once_to_learn_what_they_are(self) -> None:
        site = _FakeSite()
        index = FidlarAvaIndex(_client(site))
        [mortgage] = await index.by_instrument("2019EX000101")

        linked = await index.with_links(mortgage)
        before = len(site.searches())
        [release] = await index.by_instrument("2026EX000303")
        relinked = await index.with_links(linked)

        self.assertEqual(
            [(r.instrument_number, r.document_type, r.kind) for r in linked.references],
            [
                ("2021EX000202", "ASSIGNMENT", InstrumentKind.ASSIGNMENT),
                ("2026EX000303", "RELEASE/SATISFACTION", InstrumentKind.RELEASE),
            ],
        )
        self.assertEqual(before, 3)
        self.assertEqual(release.recorded_on, date(2026, 5, 18))
        self.assertIs(relinked, linked)
        self.assertEqual(len(site.searches()), before)

    async def test_a_link_to_a_number_not_in_the_index_stays_untyped(self) -> None:
        mortgage = _row("2019EX000101")
        mortgage["AssociatedDocuments"].append(
            {"Id": 7000999, "Name": "OR 12 345", "ImageExists": False}
        )
        site = _FakeSite(documents=[mortgage])
        index = FidlarAvaIndex(_client(site))
        [found] = await index.by_instrument("2019EX000101")

        linked = await index.with_links(found)

        self.assertEqual(
            [(r.instrument_number, r.kind) for r in linked.references],
            [
                ("2021EX000202", InstrumentKind.OTHER),
                ("2026EX000303", InstrumentKind.OTHER),
                ("OR 12 345", InstrumentKind.OTHER),
            ],
        )


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def _connector(self, site: _FakeSite | None = None) -> FidlarAvaRecorderConnector:
        return FidlarAvaRecorderConnector(CONFIG, client=_client(site or _FakeSite()))

    def test_it_is_a_release_source_for_its_county(self) -> None:
        connector = build_recorder_source_connector(CONFIG)

        self.assertIsInstance(connector, MortgageReleaseSource)
        self.assertTrue(connector.supports(EXAMPLE, SourceKind.COUNTY_RECORDER))
        self.assertFalse(connector.supports(Jurisdiction(state="XX", county="Other County")))
        self.assertEqual(connector.descriptor.base_url, APP)
        self.assertEqual(connector.descriptor.metadata["platform"], "fidlar-ava")
        self.assertFalse(connector.descriptor.requires_auth)

    async def test_a_search_needs_a_party_or_an_instrument(self) -> None:
        result = await self._connector().query(
            SourceQuery(jurisdiction=EXAMPLE, kind=SourceKind.COUNTY_RECORDER, criteria={})
        )

        self.assertIs(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)

    async def test_a_search_by_number_is_cited_and_marked_for_review(self) -> None:
        result = await self._connector().query(
            SourceQuery(
                jurisdiction=EXAMPLE,
                kind=SourceKind.COUNTY_RECORDER,
                criteria={"instrument_number": "2026EX000303"},
            )
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["instrument_number"], "2026EX000303")
        self.assertEqual(result.citations[0].recording_reference, "2026EX000303")

    async def test_a_search_by_party_reads_its_dates(self) -> None:
        site = _FakeSite()

        result = await self._connector(site).query(
            SourceQuery(
                jurisdiction=EXAMPLE,
                kind=SourceKind.COUNTY_RECORDER,
                criteria={"party_name": "Jane Sampleton", "recorded_to": "2026-06-30"},
            )
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(site.searches()[0]["EndDate"], "2026-06-30")

    async def test_the_site_failing_is_a_failed_result(self) -> None:
        class _Down(_FakeSite):
            def request(self, method, url, **kwargs):
                raise RequestsConnectionError("connection refused")

        result = await self._connector(_Down()).find_release(
            EXAMPLE, MortgageReleaseQuery(mortgage_instrument_number="2019EX000101")
        )

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("connection refused", result.warnings[0])

    async def test_a_captcha_is_a_failed_result_that_says_so(self) -> None:
        site = _FakeSite(refuse=_Answer(412, {"Message": "Precondition Failed"}))

        result = await self._connector(site).find_release(
            EXAMPLE, MortgageReleaseQuery(mortgage_instrument_number="2019EX000101")
        )

        self.assertIs(result.status, SourceResultStatus.FAILED)
        self.assertIn("FidlarAvaCaptchaRequired", result.warnings[0])
        self.assertIn("by hand", result.warnings[0])

    async def test_a_release_the_county_links_to_the_mortgage_is_found(self) -> None:
        result = await self._connector().find_release(
            EXAMPLE,
            MortgageReleaseQuery(
                mortgage_instrument_number="2019EX000101", paid_off_on="2026-05-01"
            ),
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.mortgage_release_search")
        self.assertEqual(record["record_type"], "mortgage_release_search")
        self.assertEqual(record["status"], "released")
        self.assertEqual(record["mortgage_identified_by"], "instrument_number")
        [match] = record["releases"]
        self.assertEqual(match["basis"], "index_reference")
        self.assertEqual(match["release"]["instrument_number"], "2026EX000303")
        self.assertEqual(match["release"]["recorded_on"], "2026-05-18")
        self.assertEqual(
            {c.recording_reference for c in result.citations}, {"2019EX000101", "2026EX000303"}
        )

    async def test_a_mortgage_cited_by_book_and_page_is_found_and_followed(self) -> None:
        result = await self._connector().find_release(
            EXAMPLE,
            MortgageReleaseQuery(
                mortgage_book="0912", mortgage_page="3344", paid_off_on="2026-05-01"
            ),
        )

        [record] = result.records
        self.assertEqual(record["status"], "released")
        self.assertEqual(record["mortgage_identified_by"], "book_page")
        self.assertEqual(record["mortgage"]["instrument_number"], "2019EX000101")
        [match] = record["releases"]
        self.assertEqual(match["release"]["instrument_number"], "2026EX000303")

    async def test_a_mortgage_with_no_release_linked_is_not_released(self) -> None:
        mortgage = _row("2019EX000101")
        mortgage["AssociatedDocuments"] = mortgage["AssociatedDocuments"][:1]
        site = _FakeSite(documents=[mortgage, _row("2021EX000202")])

        result = await self._connector(site).find_release(
            EXAMPLE, MortgageReleaseQuery(mortgage_instrument_number="2019EX000101")
        )

        [record] = result.records
        self.assertEqual(record["status"], "not_released")
        self.assertEqual(record["releases"], [])


if __name__ == "__main__":
    unittest.main()

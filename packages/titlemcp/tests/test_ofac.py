from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from title_mcp.domain.models import Jurisdiction
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources.base import SourceKind, SourceQuery, SourceResultStatus
from title_mcp.sources.ofac.lists import ListStore, changed, parse
from title_mcp.sources.ofac.match import Screener
from title_mcp.sources.ofac.models import (
    AliasQuality,
    Outcome,
    PartyType,
    SanctionsList,
    ScreeningParty,
)
from title_mcp.sources.ofac.normalize import tokens
from title_mcp.sources.ofac.source import OfacScreeningSourceConnector

NS = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"


def _entry(
    uid: str,
    last: str,
    kind: str,
    *,
    first: str = "",
    akas: tuple[tuple[str, str, str], ...] | list[tuple[str, str, str]] = (),
    dob: str = "",
    country: str = "",
) -> str:
    aka_xml = "".join(
        f"<aka><uid>{uid}{i}</uid><type>a.k.a.</type><category>{cat}</category>"
        f"<lastName>{alast}</lastName>"
        + (f"<firstName>{afirst}</firstName>" if afirst else "")
        + "</aka>"
        for i, (afirst, alast, cat) in enumerate(akas)
    )
    parts = [f"<sdnEntry><uid>{uid}</uid>"]
    if first:
        parts.append(f"<firstName>{first}</firstName>")
    parts.append(f"<lastName>{last}</lastName><sdnType>{kind}</sdnType>")
    parts.append("<programList><program>SDGT</program></programList>")
    if aka_xml:
        parts.append(f"<akaList>{aka_xml}</akaList>")
    if dob:
        parts.append(
            "<dateOfBirthList><dateOfBirthItem>"
            f"<uid>9{uid}</uid><dateOfBirth>{dob}</dateOfBirth>"
            "</dateOfBirthItem></dateOfBirthList>"
        )
    if country:
        parts.append(
            f"<addressList><address><uid>8{uid}</uid><country>{country}</country>"
            "</address></addressList>"
        )
    parts.append("</sdnEntry>")
    return "".join(parts)


ENTRIES = [
    _entry(
        "1",
        "QARSANI",
        "Individual",
        first="Abu",
        akas=[("Muhammad", "ZUHRANI", "strong")],
        dob="10 Dec 1948",
    ),
    _entry(
        "2",
        "BANCO ESTRELLA DEL NORTE",
        "Entity",
        akas=[("", "BEDN", "weak"), ("", "NORTHERN STAR BANK", "strong")],
        country="Spain",
    ),
    _entry("3", "SMITH", "Individual", first="John"),
    _entry("4", "GLOBAL TRADING VELMORA GROUP", "Entity"),
    _entry("5", "KESTREL ARDEN", "Vessel"),
    _entry("6", "VORANDA GARCIA", "Individual", first="Ismeral Mario", country="Mexico"),
    _entry("7", "QUANTRELL", "Individual", first="Dariusz", akas=[("Darek", "KWANTREL", "weak")]),
]


def _xml(entries: list[str], date: str = "10/02/2026") -> bytes:
    return (
        f'<?xml version="1.0"?><sdnList xmlns="{NS}"><publshInformation>'
        f"<Publish_Date>{date}</Publish_Date><Record_Count>{len(entries)}</Record_Count>"
        f"</publshInformation>{''.join(entries)}</sdnList>"
    ).encode()


class _FakeFetcher:
    def __init__(self, data: dict[str, bytes] | None = None, fail: bool = False) -> None:
        self.data = data or {}
        self.fail = fail
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        if self.fail:
            raise OSError("network unreachable")
        return self.data[url.rsplit("/", 1)[-1]]


def _screener() -> Screener:
    entries, _, _ = parse(_xml(ENTRIES), SanctionsList.SDN)
    return Screener(entries)


def _screen(name: str, kind: PartyType = PartyType.INDIVIDUAL, dob: str | None = None):
    return _screener().screen(ScreeningParty(name=name, party_type=kind, date_of_birth=dob))


class OfacListTests(unittest.TestCase):
    def test_parses_entries_aliases_and_identifiers(self) -> None:
        entries, date, count = parse(_xml(ENTRIES), SanctionsList.SDN)

        self.assertEqual((date, count, len(entries)), ("10/02/2026", 7, 7))
        bank = next(e for e in entries if e.uid == "2")
        self.assertEqual(
            [(n.full_name, n.quality) for n in bank.names],
            [
                ("BANCO ESTRELLA DEL NORTE", AliasQuality.PRIMARY),
                ("BEDN", AliasQuality.WEAK),
                ("NORTHERN STAR BANK", AliasQuality.STRONG),
            ],
        )
        qarsani = next(e for e in entries if e.uid == "1")
        self.assertEqual((qarsani.dates_of_birth, qarsani.programs), (["10 Dec 1948"], ["SDGT"]))
        self.assertEqual(bank.address_countries, ["Spain"])

    def test_entries_tagged_sanctions_entry_are_parsed_too(self) -> None:
        data = _xml(ENTRIES[:2]).replace(b"sdnEntry>", b"sanctionsEntry>")

        entries, _, _ = parse(data, SanctionsList.CONSOLIDATED)

        self.assertEqual([e.uid for e in entries], ["1", "2"])

    def test_changed_entries_are_the_new_and_the_edited(self) -> None:
        old, _, _ = parse(_xml(ENTRIES[:3]), SanctionsList.SDN)
        edited = _entry("3", "SMITH", "Individual", first="John", dob="1970")
        new, _, _ = parse(_xml([*ENTRIES[:2], edited, ENTRIES[3]]), SanctionsList.SDN)

        self.assertEqual(sorted(e.uid for e in changed(old, new)), ["3", "4"])

    def test_names_normalize_titles_particles_and_company_forms(self) -> None:
        self.assertEqual(tokens("Mr. Mohamed Al-Rashid"), ["MUHAMMAD", "AL", "RASHID"])
        self.assertEqual(tokens("Global Trading Co., L.L.C.", entity=True), ["GLOBAL", "TRADING"])


class OfacMatchingTests(unittest.TestCase):
    def test_an_exact_listed_name_is_a_potential_match(self) -> None:
        found = _screen("Abu Qarsani")

        self.assertEqual(found.outcome, Outcome.POTENTIAL_MATCH)
        self.assertEqual((found.candidates[0].uid, found.candidates[0].score), ("1", 1.0))

    def test_transliterated_and_reordered_alias_still_matches(self) -> None:
        for name in ("Mohamed Zuhrany", "ZUHRANI, Muhammad"):
            found = _screen(name)
            self.assertEqual(found.outcome, Outcome.POTENTIAL_MATCH, name)
            top = found.candidates[0]
            self.assertEqual((top.uid, top.matched_name), ("1", "Muhammad ZUHRANI"))
            self.assertTrue(top.reasons, "every candidate explains its score")

    def test_an_initial_with_a_rare_surname_is_surfaced(self) -> None:
        found = _screen("M. Zuhrani")

        self.assertIn(found.outcome, (Outcome.POTENTIAL_MATCH, Outcome.LIKELY_FALSE_POSITIVE))
        self.assertEqual(found.candidates[0].uid, "1")

    def test_a_weak_alias_alone_is_not_a_potential_match(self) -> None:
        found = _screen("BEDN", PartyType.ENTITY)

        top = found.candidates[0]
        self.assertEqual(
            (found.outcome, top.matched_name_quality),
            (Outcome.LIKELY_FALSE_POSITIVE, AliasQuality.WEAK),
        )
        self.assertTrue(any("weak alias" in r for r in top.reasons))

    def test_an_exact_match_on_a_listed_common_name_is_still_flagged(self) -> None:
        self.assertEqual(_screen("John Smith").outcome, Outcome.POTENTIAL_MATCH)

    def test_a_partial_match_on_common_names_is_not(self) -> None:
        found = _screen("Maria Garcia")

        self.assertNotEqual(found.outcome, Outcome.POTENTIAL_MATCH)

    def test_generic_company_words_do_not_make_a_match(self) -> None:
        found = _screen("Global Trading LLC", PartyType.ENTITY)

        self.assertNotEqual(found.outcome, Outcome.POTENTIAL_MATCH)

    def test_a_person_never_matches_a_vessel_or_a_company(self) -> None:
        self.assertEqual(_screen("Kestrel Arden").outcome, Outcome.NO_MATCH)
        self.assertEqual(
            _screen("Kestrel Arden Holdings LLC", PartyType.ENTITY).outcome, Outcome.NO_MATCH
        )
        self.assertEqual(
            _screen("Banco Estrella del Norte", PartyType.INDIVIDUAL).outcome, Outcome.NO_MATCH
        )

    def test_a_date_of_birth_discounts_or_corroborates(self) -> None:
        differs = _screen("Abu Qarsani", dob="1990-04-02")
        agrees = _screen("Abu Qarsani", dob="1948-12-10")

        self.assertLess(differs.candidates[0].score, 0.86 if differs.candidates else 1)
        self.assertTrue(any("differs" in r for c in differs.candidates for r in c.reasons))
        self.assertTrue(any("agrees" in r for r in agrees.candidates[0].reasons))

    def test_a_weak_alias_corroborated_by_date_of_birth_is_a_potential_match(self) -> None:
        entries, _, _ = parse(
            _xml(
                [
                    _entry(
                        "8",
                        "WEAKLY",
                        "Individual",
                        first="Primary",
                        akas=[("Dariusz", "KWANTRELL", "weak")],
                        dob="1966",
                    )
                ]
            ),
            SanctionsList.SDN,
        )
        found = Screener(entries).screen(
            ScreeningParty(
                name="Dariusz Kwantrell",
                party_type=PartyType.INDIVIDUAL,
                date_of_birth="1966-03-01",
            )
        )

        self.assertEqual(found.outcome, Outcome.POTENTIAL_MATCH)

    def test_lone_letters_and_joining_words_do_not_match(self) -> None:
        entries, _, _ = parse(
            _xml(
                [
                    _entry("10", "Q-BANK", "Entity"),
                    _entry("11", "CODE A VENTURES", "Entity"),
                    _entry("12", "PELLAR", "Individual", first="Johny"),
                    _entry("13", "THE STONE AND GAS FACTORY", "Entity"),
                    _entry("15", "BRU SHIPPING", "Entity"),
                ]
            ),
            SanctionsList.SDN,
        )
        screener = Screener(entries)
        for name, kind in (
            ("Quorvane Bank", PartyType.ENTITY),
            ("Cody A. Fenwright", PartyType.INDIVIDUAL),
            ("Z Factor Land LLC", PartyType.ENTITY),
            ("Brue Ox Investments, LLC", PartyType.ENTITY),
        ):
            found = screener.screen(ScreeningParty(name=name, party_type=kind))
            self.assertEqual(found.outcome, Outcome.NO_MATCH, name)
        # JOHN~JOHNY and PELLA~PELLAR are genuinely close: shown, labelled, never joined.
        pella = screener.screen(
            ScreeningParty(name="John M. Pella", party_type=PartyType.INDIVIDUAL)
        )
        self.assertNotEqual(pella.outcome, Outcome.POTENTIAL_MATCH)
        self.assertFalse(any("JOHNM" in t for c in pella.candidates for t in c.matched_tokens))

    def test_a_person_like_name_of_unknown_type_is_discounted_against_a_company(self) -> None:
        entries, _, _ = parse(
            _xml([_entry("14", "LORENA VASTILLO LIMITED", "Entity")]), SanctionsList.SDN
        )
        screener = Screener(entries)

        unknown = screener.screen(ScreeningParty(name="Lorena Vastillo"))

        self.assertNotEqual(unknown.outcome, Outcome.POTENTIAL_MATCH)
        self.assertTrue(
            any("looks like a person" in r for c in unknown.candidates for r in c.reasons)
        )

    def test_two_swapped_letters_are_still_a_potential_match(self) -> None:
        entries, _, _ = parse(
            _xml(
                [
                    _entry("20", "VELDORANSKI", "Individual", first="Teodor"),
                    _entry("21", "KARVENTIS SHIPPING", "Entity"),
                ]
            ),
            SanctionsList.SDN,
        )
        screener = Screener(entries)
        for name, kind in (
            ("Teodor Veldoranksi", PartyType.INDIVIDUAL),  # a swap inside a long word
            ("Teodro Veldoranski", PartyType.INDIVIDUAL),  # a swap in a short word
            ("Karvetnis Shipping Ltd", PartyType.ENTITY),
        ):
            found = screener.screen(ScreeningParty(name=name, party_type=kind))
            self.assertEqual(found.outcome, Outcome.POTENTIAL_MATCH, name)

    def test_an_initial_matches_a_name_beginning_with_al(self) -> None:
        """AL- is stripped as an alternative, never applied: ALEKSANDRINO stays whole."""

        entries, _, _ = parse(
            _xml([_entry("22", "VORONTSKIY", "Individual", first="Aleksandrino Petrovich")]),
            SanctionsList.SDN,
        )
        found = Screener(entries).screen(
            ScreeningParty(name="A. Petrovich Vorontskiy", party_type=PartyType.INDIVIDUAL)
        )

        self.assertTrue(any(t.startswith("A=") for c in found.candidates for t in c.matched_tokens))

    def test_words_that_agree_only_crosswise_and_inexactly_are_discounted(self) -> None:
        entries, _, _ = parse(
            _xml([_entry("23", "TARVELLON", "Individual", first="Corvina")]), SanctionsList.SDN
        )
        screener = Screener(entries)

        crosswise = screener.screen(
            ScreeningParty(name="Tarvelon Corvine", party_type=PartyType.INDIVIDUAL)
        )
        exact_reorder = screener.screen(
            ScreeningParty(name="TARVELLON, Corvina", party_type=PartyType.INDIVIDUAL)
        )

        self.assertNotEqual(crosswise.outcome, Outcome.POTENTIAL_MATCH)
        self.assertTrue(
            any("different order" in r for c in crosswise.candidates for r in c.reasons)
        )
        self.assertEqual(exact_reorder.outcome, Outcome.POTENTIAL_MATCH)

    def test_short_and_generic_company_names_need_more_than_a_shared_word(self) -> None:
        entries, _, _ = parse(
            _xml(
                [
                    _entry("30", "Z-FINANCE LTD", "Entity"),
                    _entry("31", "SUNDERVALE PROPERTIES LLC", "Entity"),
                    _entry("32", "PRALVA LLP", "Entity"),
                    _entry("33", "ZQV SARL", "Entity"),
                    _entry("34", "CAPITAL SERVICES GROUP", "Entity"),
                    _entry("35", "JSC VORTEK", "Entity"),
                ]
            ),
            SanctionsList.SDN,
        )
        screener = Screener(entries)
        for name in (
            "Finance, Inc.",  # only business words, against a different name
            "Sundervale LLC",  # one distinctive word; the listing has another
            "Ralvo, LLC",  # one short word, not near exact
            "ZQV Capital, LLC",  # a three-letter initialism
            "Vorteek Corporation",  # one short word, close but not exact
        ):
            found = screener.screen(ScreeningParty(name=name, party_type=PartyType.ENTITY))
            self.assertNotEqual(found.outcome, Outcome.POTENTIAL_MATCH, name)
        for name in ("Z Finance Ltd", "Capital Services Group, LLC"):  # the whole listed name
            found = screener.screen(ScreeningParty(name=name, party_type=PartyType.ENTITY))
            self.assertEqual(found.outcome, Outcome.POTENTIAL_MATCH, name)

    def test_mistyped_variants_and_legal_forms_are_still_recognised(self) -> None:
        self.assertEqual(tokens("Moahmed Tarvoni"), ["MUHAMMAD", "TARVONI"])
        self.assertEqual(tokens("Hsusein Tarvoni"), ["HUSAYN", "TARVONI"])
        self.assertEqual(
            tokens("Velquist Trading Comapny Limitde", entity=True), ["VELQUIST", "TRADING"]
        )

    def test_a_joined_name_is_compared_whole(self) -> None:
        entries, _, _ = parse(
            _xml([_entry("40", "LEFT", "Individual", first="Ondrej")]), SanctionsList.SDN
        )
        found = Screener(entries).screen(
            ScreeningParty(name="Ondrej Dorn", party_type=PartyType.INDIVIDUAL)
        )

        self.assertNotEqual(found.outcome, Outcome.POTENTIAL_MATCH)

    def test_company_words_in_another_order_are_discounted(self) -> None:
        entries, _, _ = parse(
            _xml([_entry("41", "VORELL ASTEN TRADE GMBH", "Entity")]), SanctionsList.SDN
        )
        found = Screener(entries).screen(
            ScreeningParty(name="Asten Vorell Mortgage Company, Inc.", party_type=PartyType.ENTITY)
        )

        self.assertNotEqual(found.outcome, Outcome.POTENTIAL_MATCH)
        self.assertTrue(any("different order" in r for c in found.candidates for r in c.reasons))

    def test_part_of_a_longer_listed_name_needs_an_exact_rare_word(self) -> None:
        entries, _, _ = parse(
            _xml(
                [
                    _entry("42", "MORANTE LEVISSO", "Individual", first="Joselo"),
                    _entry("43", "QARVENDISH", "Individual", first="Hamid Reza Taheri"),
                ]
            ),
            SanctionsList.SDN,
        )
        screener = Screener(entries)
        # An inexact first name and only part of the listed name: shown, not an alert.
        common = screener.screen(
            ScreeningParty(name="Jose Morante", party_type=PartyType.INDIVIDUAL)
        )
        rare = screener.screen(
            ScreeningParty(name="Hamid Qarvendish", party_type=PartyType.INDIVIDUAL)
        )

        self.assertNotEqual(common.outcome, Outcome.POTENTIAL_MATCH)
        self.assertEqual(rare.outcome, Outcome.POTENTIAL_MATCH)

    def test_an_unrelated_name_has_no_candidates(self) -> None:
        self.assertEqual(_screen("Mary Johnson").outcome, Outcome.NO_MATCH)


class OfacConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = TitleMCPSettings(ofac_cache_dir=self.tmp.name)
        self.fetcher = _FakeFetcher(
            {"SDN.XML": _xml(ENTRIES), "CONSOLIDATED.XML": _xml([], "09/14/2026")}
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def _query(self, connector: OfacScreeningSourceConnector, **criteria):
        return await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.OFFICIAL_RECORDS,
                criteria=criteria,
            )
        )

    async def test_screening_cites_each_list_and_returns_the_canonical_record(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)

        result = await self._query(
            connector,
            parties=[{"name": "Abu Qarsani", "party_type": "individual"}, {"name": "Mary Johnson"}],
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        record = result.records[0]
        self.assertEqual(
            (record["schema_name"], record["record_type"]),
            ("title_mcp.ofac_screening", "ofac_screening"),
        )
        self.assertEqual(record["outcome"], "potential_match")
        self.assertEqual([p["outcome"] for p in record["parties"]], ["potential_match", "no_match"])
        self.assertEqual(
            [c.label for c in result.citations],
            [
                "OFAC SDN list, published 10/02/2026 (7 entries)",
                "OFAC CONSOLIDATED list, published 09/14/2026 (0 entries)",
            ],
        )
        self.assertTrue(all(c.metadata["sha256"] for c in result.citations))

    async def test_changes_only_screens_against_new_and_edited_entries(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)
        await self._query(connector, parties=[{"name": "Abu Qarsani"}])
        self.fetcher.data["SDN.XML"] = _xml(
            [*ENTRIES, _entry("9", "NEWLY LISTED", "Individual", first="Some")]
        )

        result = await self._query(
            connector,
            parties=[{"name": "Abu Qarsani"}, {"name": "Some Newly Listed"}],
            changes_only=True,
            refresh=True,
        )

        outcomes = [p["outcome"] for p in result.records[0]["parties"]]
        self.assertEqual(outcomes, ["no_match", "potential_match"])
        self.assertEqual(result.records[0]["source_specific"]["entries_screened_against"], 1)

    async def test_no_list_and_no_network_is_a_reported_failure(self) -> None:
        connector = OfacScreeningSourceConnector(
            settings=self.settings, fetcher=_FakeFetcher(fail=True)
        )

        result = await self._query(connector, parties=[{"name": "Abu Qarsani"}])

        self.assertEqual(result.status, SourceResultStatus.FAILED)
        self.assertIn("sanctionslistservice.ofac.treas.gov", result.warnings[0])

    async def test_a_stale_copy_is_used_and_said_to_be_stale(self) -> None:
        ListStore(Path(self.tmp.name), fetcher=self.fetcher).load(SanctionsList.SDN)
        ListStore(Path(self.tmp.name), fetcher=self.fetcher).load(SanctionsList.CONSOLIDATED)
        old = time.time() - 5 * 86400
        for f in Path(self.tmp.name).glob("*.XML"):
            os.utime(f, (old, old))
        connector = OfacScreeningSourceConnector(
            settings=self.settings, fetcher=_FakeFetcher(fail=True)
        )

        result = await self._query(connector, parties=[{"name": "Abu Qarsani"}])

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(any("days old" in w for w in result.warnings))

    async def test_a_party_date_of_birth_is_echoed_as_the_year_only(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)

        result = await self._query(
            connector, parties=[{"name": "Abu Qarsani", "date_of_birth": "1948-12-10"}]
        )

        echoed = result.records[0]["parties"][0]["party"]["date_of_birth"]
        self.assertEqual(echoed, "1948")
        self.assertNotIn("1948-12-10", str(result.model_dump(mode="json")))

    async def test_a_corrupt_download_never_replaces_a_good_copy(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)
        await self._query(connector, parties=[{"name": "Abu Qarsani"}])
        self.fetcher.data["SDN.XML"] = b"<html>Service temporarily unavailable</html>"

        result = await self._query(connector, parties=[{"name": "Abu Qarsani"}], refresh=True)

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(result.records[0]["parties"][0]["outcome"], "potential_match")
        self.assertIn(b"<sdnList", (Path(self.tmp.name) / "SDN.XML").read_bytes())

    async def test_the_record_carries_its_source(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)

        record = (await self._query(connector, parties=[{"name": "Mary Johnson"}])).records[0]

        self.assertEqual(record["source"]["source_id"], "us-federal-ofac-sanctions")
        self.assertEqual(record["source"]["list_publish_dates"]["sdn"], "10/02/2026")

    async def test_list_status_reports_unavailable_lists_without_raising(self) -> None:
        from title_mcp.sources.ofac.source import list_status

        offline = OfacScreeningSourceConnector(
            settings=self.settings, fetcher=_FakeFetcher(fail=True)
        )
        status = list_status(offline)

        self.assertEqual((status["status"], status["lists"]), ("failed", []))
        self.assertEqual(len(status["warnings"]), 2)

        online = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)
        self.assertEqual(list_status(online)["status"], "succeeded")

    async def test_an_invalid_request_is_a_reported_failure(self) -> None:
        connector = OfacScreeningSourceConnector(settings=self.settings, fetcher=self.fetcher)

        result = await self._query(connector, parties=[])

        self.assertEqual(result.status, SourceResultStatus.FAILED)


if __name__ == "__main__":
    unittest.main()

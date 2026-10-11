from __future__ import annotations

import json
import unittest
from datetime import date

from pydantic import ValidationError

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import (
    InstrumentKind,
    InstrumentReference,
    MortgageIdentifiedBy,
    MortgageReleaseQuery,
    RecordedInstrument,
    ReleaseFindingStatus,
    ReleaseMatchBasis,
    classify_instrument,
    index_search_name,
    same_party,
)
from title_mcp.mcp.server import create_mcp_server
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import (
    MortgageReleaseSource,
    SourceDescriptor,
    SourceKind,
    SourceResult,
    SourceResultStatus,
    find_mortgage_release,
    release_source_result,
)
from title_mcp.state.memory import InMemoryWorkflowRepository

MORTGAGE = "202001150101"
RELEASE = "202605200202"


def _mortgage(*, references: list[InstrumentReference] | None = None) -> RecordedInstrument:
    return RecordedInstrument(
        instrument_number=MORTGAGE,
        recorded_on=date(2020, 1, 15),
        document_type="MORT - MORTGAGE",
        kind=InstrumentKind.MORTGAGE,
        grantors=["DOE JANE", "DOE JOHN"],
        grantees=["SAMPLE SAVINGS BANK", "MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        references=references or [],
    )


def _release(
    number: str = RELEASE,
    *,
    recorded_on: date = date(2026, 5, 20),
    document_type: str = "RELS - RELEASE SATISFACTION",
    references: list[str] | None = None,
    text: str = "",
    grantors: list[str] | None = None,
) -> RecordedInstrument:
    return RecordedInstrument(
        instrument_number=number,
        recorded_on=recorded_on,
        document_type=document_type,
        kind=classify_instrument(document_type),
        grantors=grantors or ["SAMPLE SAVINGS BANK"],
        grantees=["DOE JANE", "DOE JOHN"],
        references=[
            InstrumentReference(instrument_number=n, document_type="MORT - MORTGAGE")
            for n in references or []
        ],
        text_excerpt=text,
    )


class _FakeIndex:
    """A county index over a fixed list of documents."""

    def __init__(self, documents: list[RecordedInstrument]) -> None:
        self.documents = documents
        self.calls: list[tuple[str, str]] = []

    async def by_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        self.calls.append(("by_instrument", instrument_number))
        return [d for d in self.documents if d.instrument_number == instrument_number]

    async def by_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        self.calls.append(("by_book_page", f"{book}/{page}"))
        return [d for d in self.documents if (d.book, d.page) == (book, page)]

    async def citing(self, instrument_number: str) -> list[RecordedInstrument]:
        self.calls.append(("citing", instrument_number))
        return [
            d
            for d in self.documents
            if d.cites(instrument_number) or instrument_number in d.text_excerpt
        ]

    async def with_links(self, document: RecordedInstrument) -> RecordedInstrument:
        return document

    async def by_party(
        self, name: str, *, recorded_from: date | None = None
    ) -> list[RecordedInstrument]:
        self.calls.append(("by_party", name))
        return [
            d
            for d in self.documents
            if any(same_party(name, party) for party in d.grantors + d.grantees)
            and (recorded_from is None or (d.recorded_on and d.recorded_on >= recorded_from))
        ]


class InstrumentClassificationTests(unittest.TestCase):
    def test_county_vocabularies_map_to_one_set_of_kinds(self) -> None:
        cases = {
            "RELS - RELEASE SATISFACTION": InstrumentKind.RELEASE,
            "MORTGAGE RELEASE": InstrumentKind.RELEASE,
            "SATISFACTION OF MORTGAGE": InstrumentKind.RELEASE,
            "PARTIAL RELEASE OF MORTGAGE": InstrumentKind.PARTIAL_RELEASE,
            "MORT - MORTGAGE": InstrumentKind.MORTGAGE,
            "MTGE": InstrumentKind.MORTGAGE,
            "MORTGAGE ASSIGNMENT": InstrumentKind.ASSIGNMENT,
            "WARRANTY DEED": InstrumentKind.DEED,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)

    def test_abbreviated_and_reordered_descriptions_read_the_same(self) -> None:
        cases = {
            "RELEASE MORTGAGE": InstrumentKind.RELEASE,
            "MORTGAGE RELEASE N/C": InstrumentKind.RELEASE,
            "PT REL MORTGAGE": InstrumentKind.PARTIAL_RELEASE,
            "REL AMEND MORTGAGE": InstrumentKind.RELEASE,
            "ASSN MORTGAGE": InstrumentKind.ASSIGNMENT,
            "COURT RELEASE": InstrumentKind.RELEASE,
            "RELEASE": InstrumentKind.RELEASE,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)

    def test_releases_of_other_things_are_not_mortgage_releases(self) -> None:
        for description in (
            "LEASE RELEASE",
            "FEDERAL TAX LIEN RELEASE",
            "RIGHT OF WAY RELEASE",
            "LRLS - LIEN RELEASE",
            "REL ASSN MORTGAGE",
            "RESCISSION OF REL OF MTG",
            "UCC PARTIAL RELEASE",
            # Texas counties whose plain RELEASE OF LIEN is a deed of trust's
            # release say so in their site config; elsewhere it is not.
            "RELEASE OF LIEN",
            "RECONVEYANCE OF EASEMENT",
        ):
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), InstrumentKind.OTHER)

    def test_documents_that_only_contain_the_words_are_not_mortgage_releases(self) -> None:
        # Each of these contains MORTGAGE or RELEASE without being either.
        cases = {
            "MODIFICATION OF MORTGAGE": InstrumentKind.MODIFICATION,
            "RELA - RELEASE ASSIGNMENT": InstrumentKind.OTHER,
            "ASSIGNMENT OF RENTS RELEASE": InstrumentKind.OTHER,
            "COURT ENTRY/LIS PENDENS RELEASE": InstrumentKind.OTHER,
            "UCC TERMINATION": InstrumentKind.OTHER,
            "CHATTEL MORTGAGE/FINANCING STATEMENT": InstrumentKind.OTHER,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)

    def test_a_deed_of_trust_reads_as_the_mortgage(self) -> None:
        cases = {
            "DEED OF TRUST": InstrumentKind.MORTGAGE,
            "DT - DEED OF TRUST": InstrumentKind.MORTGAGE,
            "CORRECTION DEED OF TRUST": InstrumentKind.MORTGAGE,
            "DEED OF TRUST & SECURITY AGREEMENT": InstrumentKind.MORTGAGE,
            "TRUST DEED/OF (MTG)": InstrumentKind.MORTGAGE,
            "RELEASE OF DEED OF TRUST": InstrumentKind.RELEASE,
            "PARTIAL RELEASE OF DEED OF TRUST": InstrumentKind.PARTIAL_RELEASE,
            "REL D/T": InstrumentKind.RELEASE,
            "REL DOT": InstrumentKind.RELEASE,
            "ASSIGNMENT OF DEED OF TRUST": InstrumentKind.ASSIGNMENT,
            "MODIFICATION OF DEED OF TRUST": InstrumentKind.MODIFICATION,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)

    def test_conveyances_in_trust_are_not_deeds_of_trust(self) -> None:
        cases = {
            "DEED-IN TRUST": InstrumentKind.DEED,
            "TRUSTEE'S/SUBSTITUTE TRUSTEE'S DEED": InstrumentKind.DEED,
            "PUBLIC TRUSTEE'S DEED": InstrumentKind.DEED,
            "DECLARATION OF TRUST": InstrumentKind.OTHER,
            "APPOINTMENT OF TRUSTEE/SUBSTITUTE TRUSTEE": InstrumentKind.OTHER,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)

    def test_a_reconveyance_releases_the_deed_of_trust(self) -> None:
        cases = {
            "FULL RECONVEYANCE": InstrumentKind.RELEASE,
            "DEED OF RECONVEYANCE": InstrumentKind.RELEASE,
            "SUBSTITUTION OF TRUSTEE AND FULL RECONVEYANCE": InstrumentKind.RELEASE,
            "PARTIAL RECONVEYANCE": InstrumentKind.PARTIAL_RELEASE,
            "SATISFACTION OF MORTGAGE BY AFFIDAVIT": InstrumentKind.RELEASE,
        }
        for description, kind in cases.items():
            with self.subTest(description=description):
                self.assertIs(classify_instrument(description), kind)


class PartyMatchingTests(unittest.TestCase):
    def test_a_person_matches_in_either_name_order(self) -> None:
        self.assertTrue(same_party("JANE DOE", "DOE JANE M"))

    def test_index_abbreviations_match_the_lender(self) -> None:
        self.assertTrue(same_party("SAMPLE NATIONAL BANK", "SAMPLE NATL BK ETAL"))

    def test_different_people_with_one_surname_do_not_match(self) -> None:
        self.assertFalse(same_party("JANE DOE", "DOE JOHN"))


class SearchNameTests(unittest.TestCase):
    def test_qualifiers_initials_and_punctuation_are_dropped(self) -> None:
        cases = {
            "Jane D. Doe": "JANE DOE",
            "John Doe, a widower": "JOHN DOE",
            "Jane Doe, as Trustee of the Doe Family Trust": "JANE DOE",
            "JOHN DOE AKA JACK DOE": "JOHN DOE",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(index_search_name(name), expected)

    def test_a_business_keeps_its_suffix(self) -> None:
        self.assertEqual(index_search_name("Sample Homes, LLC"), "SAMPLE HOMES LLC")


class QueryTests(unittest.TestCase):
    def test_names_are_upper_cased_as_the_index_stores_them(self) -> None:
        query = MortgageReleaseQuery(borrower_names=[" Jane Doe ", ""], lender_names=["Sample"])

        self.assertEqual(query.borrower_names, ["JANE DOE"])
        self.assertEqual(query.lender_names, ["SAMPLE"])

    def test_an_address_alone_is_not_enough_to_search(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            MortgageReleaseQuery(lender_names=["SAMPLE SAVINGS BANK"])

        self.assertIn("street address", str(caught.exception))


class FindReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_release_the_index_links_to_the_mortgage_is_the_answer(self) -> None:
        mortgage = _mortgage(
            references=[
                InstrumentReference(
                    instrument_number=RELEASE,
                    document_type="RELS - RELEASE SATISFACTION",
                    kind=InstrumentKind.RELEASE,
                )
            ]
        )
        index = _FakeIndex([mortgage, _release(references=[MORTGAGE])])

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, MORTGAGE)
        [match] = finding.releases
        self.assertIs(match.basis, ReleaseMatchBasis.INDEX_REFERENCE)
        # The release was looked up, so its recorded date is known.
        self.assertEqual(match.release.recorded_on, date(2026, 5, 20))
        self.assertNotIn(("by_party", "DOE JANE"), index.calls)

    async def test_a_deed_of_trust_is_released_like_a_mortgage(self) -> None:
        deed_of_trust = RecordedInstrument(
            instrument_number=MORTGAGE,
            recorded_on=date(2020, 1, 15),
            document_type="DEED OF TRUST",
            kind=classify_instrument("DEED OF TRUST"),
            grantors=["DOE JANE"],
            grantees=["SAMPLE SAVINGS BANK"],
            references=[
                InstrumentReference(
                    instrument_number=RELEASE,
                    document_type="RELEASE OF DEED OF TRUST",
                    kind=classify_instrument("RELEASE OF DEED OF TRUST"),
                )
            ],
        )
        release = _release(document_type="RELEASE OF DEED OF TRUST", references=[MORTGAGE])
        index = _FakeIndex([deed_of_trust, release])

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        [match] = finding.releases
        self.assertIs(match.basis, ReleaseMatchBasis.INDEX_REFERENCE)

    async def test_a_reference_of_another_kind_is_not_mistaken_for_a_release(self) -> None:
        mortgage = _mortgage(
            references=[
                InstrumentReference(
                    instrument_number="202101010303",
                    document_type="A/M - MORTGAGE ASSIGNMENT",
                    kind=InstrumentKind.ASSIGNMENT,
                )
            ]
        )

        finding = await find_mortgage_release(
            _FakeIndex([mortgage]), MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.NOT_RELEASED)
        self.assertIn("can take days or weeks", " ".join(finding.notes))

    async def test_a_release_whose_text_cites_the_mortgage_is_found_without_a_link(self) -> None:
        release = _release(text=f"releases the mortgage recorded as Instrument No. {MORTGAGE}")
        index = _FakeIndex([_mortgage(), release])

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertIs(finding.releases[0].basis, ReleaseMatchBasis.TEXT_REFERENCE)

    async def test_an_unindexed_mortgage_can_still_be_found_released(self) -> None:
        # The release links to the mortgage, but the mortgage itself is not in the index.
        index = _FakeIndex([_release(references=[MORTGAGE])])

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertIsNone(finding.mortgage)
        self.assertIs(finding.releases[0].basis, ReleaseMatchBasis.INDEX_REFERENCE)
        self.assertIn(f"No instrument {MORTGAGE} is in the index", " ".join(finding.notes))

    async def test_only_partial_releases_is_not_a_release_of_the_mortgage(self) -> None:
        partial = _release(document_type="PARTIAL RELEASE OF MORTGAGE", references=[MORTGAGE])
        index = _FakeIndex([_mortgage(), partial])

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        )

        self.assertIs(finding.status, ReleaseFindingStatus.PARTIALLY_RELEASED)

    async def test_a_release_recorded_before_the_payoff_is_flagged(self) -> None:
        early = _release(recorded_on=date(2024, 3, 1), references=[MORTGAGE])
        index = _FakeIndex([_mortgage(), early])

        finding = await find_mortgage_release(
            index,
            MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE, paid_off_on="2026-05-01"),
        )

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertIn("before the payoff on 2026-05-01", " ".join(finding.notes))

    async def test_name_matches_are_candidates_never_an_answer(self) -> None:
        index = _FakeIndex(
            [
                _mortgage(),
                _release(),
                # Same parties, but recorded before the payoff.
                _release("201801010404", recorded_on=date(2018, 1, 1)),
                # Same parties, but the index ties it to a different mortgage.
                _release("202606010505", references=["201001010606"]),
                # Released by another lender.
                _release("202606020707", grantors=["OTHER COMMUNITY BANK"]),
            ]
        )

        finding = await find_mortgage_release(
            index,
            MortgageReleaseQuery(
                mortgage_instrument_number=MORTGAGE,
                borrower_names=["Jane Doe"],
                paid_off_on="2026-05-01",
            ),
        )

        self.assertIs(finding.status, ReleaseFindingStatus.CANDIDATES_ONLY)
        self.assertEqual([m.release.instrument_number for m in finding.candidates], [RELEASE])
        self.assertIs(finding.candidates[0].basis, ReleaseMatchBasis.PARTY_MATCH)
        self.assertIn("nothing in the index ties them", " ".join(finding.notes))

    async def test_without_the_mortgage_the_lender_and_payoff_narrow_the_names(self) -> None:
        index = _FakeIndex(
            [
                _release(),
                _release("201801010404", recorded_on=date(2018, 1, 1)),
                _release("202606020707", grantors=["OTHER COMMUNITY BANK"]),
            ]
        )

        finding = await find_mortgage_release(
            index,
            MortgageReleaseQuery(
                borrower_names=["Jane Doe"],
                lender_names=["Sample Savings Bank"],
                paid_off_on="2026-05-01",
            ),
        )

        self.assertIs(finding.status, ReleaseFindingStatus.CANDIDATES_ONLY)
        self.assertEqual([m.release.instrument_number for m in finding.candidates], [RELEASE])

    async def test_a_missing_mortgage_with_nothing_else_to_go_on(self) -> None:
        finding = await find_mortgage_release(
            _FakeIndex([]), MortgageReleaseQuery(mortgage_instrument_number="1999-0001")
        )

        self.assertIs(finding.status, ReleaseFindingStatus.MORTGAGE_NOT_FOUND)


def _linked(
    mortgage_number: str,
    recorded_on: date,
    *,
    lender: str = "SAMPLE SAVINGS BANK",
    released_by: tuple[str, date] | None = None,
) -> list[RecordedInstrument]:
    """A borrower's mortgage, and its release when there is one, linked both ways."""
    references = []
    documents = []
    if released_by is not None:
        number, released_on = released_by
        references.append(
            InstrumentReference(
                instrument_number=number,
                document_type="RELS - RELEASE SATISFACTION",
                kind=InstrumentKind.RELEASE,
            )
        )
        documents.append(
            _release(
                number, recorded_on=released_on, references=[mortgage_number], grantors=[lender]
            )
        )
    mortgage = RecordedInstrument(
        instrument_number=mortgage_number,
        recorded_on=recorded_on,
        document_type="MORT - MORTGAGE",
        kind=InstrumentKind.MORTGAGE,
        grantors=["DOE JANE"],
        grantees=[lender],
        references=references,
    )
    return [mortgage, *documents]


class BorrowerMortgageTests(unittest.IsolatedAsyncioTestCase):
    """Without the mortgage's number, the payoff date picks it out."""

    def _query(self, **overrides) -> MortgageReleaseQuery:
        return MortgageReleaseQuery(
            **{"borrower_names": ["Jane Doe"], "paid_off_on": "2026-05-01", **overrides}
        )

    async def test_the_one_mortgage_open_at_the_payoff_is_the_one_paid_off(self) -> None:
        index = _FakeIndex(
            # Refinanced away in 2020: released before the payoff, so not this one.
            _linked(
                "201501010101", date(2015, 1, 1), released_by=("202003030303", date(2020, 3, 3))
            )
            + _linked("202002020202", date(2020, 2, 2), released_by=(RELEASE, date(2026, 5, 20)))
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "202002020202")
        self.assertIs(finding.mortgage_identified_by, MortgageIdentifiedBy.PARTIES)
        self.assertEqual([m.release.instrument_number for m in finding.releases], [RELEASE])
        self.assertIn("not by its number", " ".join(finding.notes))
        self.assertEqual(
            [(b.mortgage.instrument_number, b.open_at_payoff) for b in finding.borrower_mortgages],
            [("202002020202", True), ("201501010101", False)],
        )

    async def test_an_open_mortgage_with_nothing_linked_is_not_released(self) -> None:
        index = _FakeIndex(_linked("202002020202", date(2020, 2, 2)))

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.NOT_RELEASED)
        self.assertIs(finding.mortgage_identified_by, MortgageIdentifiedBy.PARTIES)

    async def test_of_two_open_mortgages_the_one_released_since_is_the_one_paid_off(
        self,
    ) -> None:
        # An old mortgage whose release predates the county's links looks open.
        index = _FakeIndex(
            _linked("199805050505", date(1998, 5, 5))
            + _linked("202002020202", date(2020, 2, 2), released_by=(RELEASE, date(2026, 5, 20)))
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "202002020202")
        self.assertIn("released since the payoff", " ".join(finding.notes))

    async def test_open_mortgages_with_no_release_since_are_not_released(self) -> None:
        index = _FakeIndex(
            _linked("199805050505", date(1998, 5, 5))
            + _linked("202104040404", date(2021, 4, 4), lender="OTHER COMMUNITY BANK")
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.NOT_RELEASED)
        self.assertIsNone(finding.mortgage)
        self.assertIn("None of them shows a release since the payoff", " ".join(finding.notes))

    async def test_without_links_the_release_citing_a_mortgage_picks_it_out(self) -> None:
        # A county that links nothing: the release says which deed of trust it
        # releases only in its text.
        index = _FakeIndex(
            _linked("199805050505", date(1998, 5, 5))
            + _linked("202104040404", date(2021, 4, 4))
            + [_release(text="releases the deed of trust recorded as 202104040404")]
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "202104040404")
        [match] = finding.releases
        self.assertIs(match.basis, ReleaseMatchBasis.TEXT_REFERENCE)

    async def test_without_links_or_text_an_unlinked_release_is_a_candidate(self) -> None:
        index = _FakeIndex(
            _linked("199805050505", date(1998, 5, 5))
            + _linked("202104040404", date(2021, 4, 4))
            + [_release()]
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.CANDIDATES_ONLY)
        self.assertEqual([c.release.instrument_number for c in finding.candidates], [RELEASE])
        self.assertIs(finding.candidates[0].basis, ReleaseMatchBasis.PARTY_MATCH)

    async def test_a_release_the_index_ties_to_another_document_is_not_a_candidate(
        self,
    ) -> None:
        index = _FakeIndex(
            _linked("199805050505", date(1998, 5, 5))
            + _linked("202104040404", date(2021, 4, 4))
            + [_release(references=["201707070707"])]
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.NOT_RELEASED)
        self.assertEqual(finding.candidates, [])

    async def test_two_released_since_are_candidates_not_a_guess(self) -> None:
        index = _FakeIndex(
            _linked("202002020202", date(2020, 2, 2), released_by=(RELEASE, date(2026, 5, 20)))
            + _linked(
                "202104040404",
                date(2021, 4, 4),
                lender="OTHER COMMUNITY BANK",
                released_by=("202606110808", date(2026, 6, 11)),
            )
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.CANDIDATES_ONLY)
        self.assertIsNone(finding.mortgage)
        self.assertEqual(
            sorted(m.release.instrument_number for m in finding.candidates),
            [RELEASE, "202606110808"],
        )

    async def test_one_release_of_two_linked_mortgages_is_one_release(self) -> None:
        index = _FakeIndex(
            _linked("201209090909", date(2012, 9, 9), released_by=(RELEASE, date(2026, 5, 20)))
            + _linked("201512121212", date(2015, 12, 12), released_by=(RELEASE, date(2026, 5, 20)))
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "201512121212")

    async def test_a_common_name_does_not_hide_the_borrowers_own_mortgage(self) -> None:
        # Seven namesakes' newer mortgages, and the borrower's older one, released since.
        namesakes = [
            document
            for year in range(2018, 2025)
            for document in _linked(f"{year}01010{year % 10}00", date(year, 1, 1))
        ]
        index = _FakeIndex(
            namesakes
            + _linked("201001010101", date(2010, 1, 1), released_by=(RELEASE, date(2026, 5, 20)))
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertIs(finding.status, ReleaseFindingStatus.RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "201001010101")
        self.assertIn("A common name matches other people's", " ".join(finding.notes))

    async def test_the_lender_picks_between_open_mortgages(self) -> None:
        index = _FakeIndex(
            _linked("202002020202", date(2020, 2, 2))
            + _linked("202104040404", date(2021, 4, 4), lender="OTHER COMMUNITY BANK")
        )

        finding = await find_mortgage_release(
            index, self._query(lender_names=["Sample Savings Bank"])
        )

        self.assertIs(finding.status, ReleaseFindingStatus.NOT_RELEASED)
        self.assertEqual(finding.mortgage.instrument_number, "202002020202")
        self.assertIn("the lender the payoff went to", " ".join(finding.notes))

    async def test_a_loan_recorded_on_the_payoff_date_is_not_the_one_paid_off(self) -> None:
        # The seller's loan on their next home is recorded the day of the payoff.
        index = _FakeIndex(
            _linked("202002020202", date(2020, 2, 2), released_by=(RELEASE, date(2026, 5, 20)))
            + _linked("202605010909", date(2026, 5, 1))
        )

        finding = await find_mortgage_release(index, self._query())

        self.assertEqual(finding.mortgage.instrument_number, "202002020202")
        self.assertEqual(
            [b.mortgage.instrument_number for b in finding.borrower_mortgages], ["202002020202"]
        )

    async def test_without_a_payoff_date_names_only_give_candidates(self) -> None:
        index = _FakeIndex(
            _linked("202002020202", date(2020, 2, 2), released_by=(RELEASE, date(2026, 5, 20)))
        )

        finding = await find_mortgage_release(
            index, MortgageReleaseQuery(borrower_names=["Jane Doe"])
        )

        self.assertIs(finding.status, ReleaseFindingStatus.CANDIDATES_ONLY)
        self.assertIn("Without the payoff date", " ".join(finding.notes))


class SourceResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_finding_becomes_a_canonical_record_marked_for_review(self) -> None:
        mortgage = _mortgage(
            references=[
                InstrumentReference(
                    instrument_number=RELEASE, document_type="RELS", kind=InstrumentKind.RELEASE
                )
            ]
        )
        query = MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        finding = await find_mortgage_release(_FakeIndex([mortgage, _release()]), query)

        result = release_source_result(
            descriptor=_FakeReleaseSource.descriptor,
            jurisdiction=Jurisdiction(state="OH", county="Sample County"),
            query=query,
            finding=finding,
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.mortgage_release_search")
        self.assertEqual(record["record_type"], "mortgage_release_search")
        self.assertEqual(record["status"], "released")
        self.assertEqual(record["source"]["source_id"], "fake-sample-recorder")
        self.assertEqual([c.recording_reference for c in result.citations], [MORTGAGE, RELEASE])

    async def test_a_mortgage_not_found_is_no_results(self) -> None:
        query = MortgageReleaseQuery(mortgage_instrument_number=MORTGAGE)
        finding = await find_mortgage_release(_FakeIndex([]), query)

        result = release_source_result(
            descriptor=_FakeReleaseSource.descriptor,
            jurisdiction=Jurisdiction(state="OH", county="Sample County"),
            query=query,
            finding=finding,
        )

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)


class _FakeReleaseSource:
    source_id = "fake-sample-recorder"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Sample County Recorder",
        kind=SourceKind.COUNTY_RECORDER,
        jurisdiction_scope=JurisdictionScope(country="US", state="OH", county="Sample County"),
    )

    def __init__(self) -> None:
        self.queries: list[MortgageReleaseQuery] = []

    def supports(self, jurisdiction, kind=None) -> bool:
        return (kind is None or kind == SourceKind.COUNTY_RECORDER) and (
            self.descriptor.jurisdiction_scope.matches(jurisdiction)
        )

    async def query(self, query):  # pragma: no cover - not used by the release tool
        raise NotImplementedError

    async def find_release(self, jurisdiction, query) -> SourceResult:
        self.queries.append(query)
        return SourceResult(source_id=self.source_id, status=SourceResultStatus.SUCCEEDED)


class MortgageReleaseToolTests(unittest.IsolatedAsyncioTestCase):
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
        result = await server.call_tool("mortgage_release_search", arguments)
        return json.loads(result.content[0].text)

    async def test_a_recorder_that_can_check_releases_is_recognized(self) -> None:
        self.assertIsInstance(_FakeReleaseSource(), MortgageReleaseSource)

    async def test_the_county_is_routed_whether_or_not_it_says_county(self) -> None:
        source = _FakeReleaseSource()
        server = self._server(source)

        result = await self._call(
            server,
            state="oh",
            county="Sample",
            mortgage_instrument_number=MORTGAGE,
            paid_off_on="2026-05-01",
        )

        self.assertEqual(result["status"], "succeeded")
        [query] = source.queries
        self.assertEqual(query.mortgage_instrument_number, MORTGAGE)
        self.assertEqual(query.paid_off_on, date(2026, 5, 1))

    async def test_a_county_without_a_recorder_connector_needs_configuration(self) -> None:
        server = self._server(_FakeReleaseSource())

        result = await self._call(
            server, state="OH", county="Elsewhere County", mortgage_instrument_number=MORTGAGE
        )

        self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("Elsewhere County, OH", result["warnings"][0])

    async def test_nothing_to_search_for_needs_configuration_not_an_error(self) -> None:
        server = self._server(_FakeReleaseSource())

        result = await self._call(server, state="OH", county="Sample County")

        self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("street address", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()

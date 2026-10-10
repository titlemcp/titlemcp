"""Finding the release of a mortgage in a county recorder's index.

The method is the same whichever platform a county runs, so it lives here, and
each recorder connector supplies a ``RecorderIndex``: the few lookups its
platform can answer. Evidence is tried strongest first.

1. **The county links the documents.** Kofile's PublicSearch counties record a
   reference on a mortgage to each document that releases it, and on the
   release back to the mortgage. Look the mortgage up and follow its
   references; a release among them is the answer.
2. **The release cites the mortgage.** Where the index carries no link, a
   search of the text read off the document images finds releases that name
   the mortgage's instrument number.
3. **The borrower's mortgages.** Without the mortgage's number, the payoff date
   narrows it down. Of the mortgages the borrower gave before it, those with no
   release recorded before the payoff could be the one paid off, and each is
   checked as in 1. The one released since the payoff is taken to be it, or
   failing that the one to the lender named, or the only one open. The record
   says the mortgage was identified that way, and lists the others.
4. **The same parties.** A release recorded after the payoff that names the
   borrower and the lender. This is only ever a candidate: a borrower with two
   loans from one bank has two releases, and nothing in the index says which
   is which.

Nothing here decides that a lien is gone. It reports what the record shows and
marks it for review.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import (
    BorrowerMortgage,
    InstrumentKind,
    MortgageIdentifiedBy,
    MortgageReleaseQuery,
    MortgageReleaseRecord,
    RecordedInstrument,
    RecorderSource,
    ReleaseFindingStatus,
    ReleaseMatch,
    ReleaseMatchBasis,
    normalize_instrument_number,
    same_party,
)
from title_mcp.sources.base import (
    SourceCitation,
    SourceDescriptor,
    SourceResult,
    SourceResultStatus,
)

RELEASE_KINDS = frozenset({InstrumentKind.RELEASE, InstrumentKind.PARTIAL_RELEASE})

#: How many of a borrower's mortgages, most recent first, are checked for a
#: release. Each costs a lookup per linked document.
MAX_BORROWER_MORTGAGES = 6


@runtime_checkable
class RecorderIndex(Protocol):
    """The lookups a county recorder platform can answer.

    A platform that cannot do one returns an empty list rather than raising, and
    the method falls through to the next kind of evidence.
    """

    async def by_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        """Documents whose instrument number is this one."""
        ...

    async def by_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        """Documents recorded at this book and page."""
        ...

    async def citing(self, instrument_number: str) -> list[RecordedInstrument]:
        """Documents whose index entry or text cites this instrument number."""
        ...

    async def by_party(
        self, name: str, *, recorded_from: date | None = None
    ) -> list[RecordedInstrument]:
        """Documents naming this party, recorded on or after a date."""
        ...


@runtime_checkable
class MortgageReleaseSource(Protocol):
    """A recorder connector that can say whether a mortgage was released."""

    source_id: str
    descriptor: SourceDescriptor

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        """Whether this connector covers the jurisdiction."""
        ...

    async def find_release(
        self, jurisdiction: Jurisdiction, query: MortgageReleaseQuery
    ) -> SourceResult:
        """Look for the release of one mortgage."""
        ...


class ReleaseFinding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: ReleaseFindingStatus
    mortgage: RecordedInstrument | None = None
    mortgage_identified_by: MortgageIdentifiedBy | None = None
    releases: list[ReleaseMatch] = Field(default_factory=list)
    borrower_mortgages: list[BorrowerMortgage] = Field(default_factory=list)
    candidates: list[ReleaseMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


async def find_mortgage_release(
    index: RecorderIndex, query: MortgageReleaseQuery
) -> ReleaseFinding:
    """Whether the county's index shows a release of the queried mortgage."""
    notes: list[str] = []
    mortgage, identified_by = await _find_mortgage(index, query, notes)

    releases: list[ReleaseMatch] = []
    if mortgage is not None:
        releases = await _referenced_releases(index, mortgage)
    number = mortgage.instrument_number if mortgage else query.mortgage_instrument_number
    if not releases and number:
        # The mortgage may not be indexed yet, or its index entry may carry no
        # links. A release can still cite it.
        releases = await _citing_releases(index, number)

    borrower_mortgages: list[BorrowerMortgage] = []
    if mortgage is None and not releases and query.borrower_names:
        borrower_mortgages = await _borrower_mortgages(index, query, notes)
        chosen, why = _the_paid_off_mortgage(borrower_mortgages, query)
        if chosen is not None:
            mortgage, identified_by = chosen.mortgage, MortgageIdentifiedBy.PARTIES
            releases = chosen.releases
            notes.append(
                f"Mortgage {mortgage.instrument_number} was identified from the borrower's "
                f"mortgages as {why}, not by its number. Confirm it against the commitment."
            )

    candidates: list[ReleaseMatch] = []
    if borrower_mortgages and mortgage is None:
        # Several were open and more than one has been released since: the
        # payoff is likely among them, but which one can't be told.
        candidates = [
            match
            for entry in borrower_mortgages
            if entry.open_at_payoff and entry.released
            for match in entry.releases
        ]
    elif not releases and not borrower_mortgages and query.borrower_names:
        candidates = await _party_candidates(index, query, mortgage, notes)

    status = _status(mortgage, releases, candidates, borrower_mortgages)
    notes.extend(_status_notes(status, query, mortgage, releases, borrower_mortgages))
    return ReleaseFinding(
        status=status,
        mortgage=mortgage,
        mortgage_identified_by=identified_by,
        releases=releases,
        borrower_mortgages=borrower_mortgages,
        candidates=candidates,
        notes=notes,
    )


def release_source_result(
    *,
    descriptor: SourceDescriptor,
    jurisdiction: Jurisdiction,
    query: MortgageReleaseQuery,
    finding: ReleaseFinding,
    source_url: str | None = None,
) -> SourceResult:
    """The finding as a canonical record, with a citation for each document."""
    retrieved_at = datetime.now(UTC).isoformat()
    record = MortgageReleaseRecord(
        source=RecorderSource(
            source_id=descriptor.source_id,
            source_name=descriptor.name,
            source_url=source_url or descriptor.base_url,
            retrieved_at=retrieved_at,
        ),
        jurisdiction=jurisdiction,
        query=query,
        status=finding.status,
        mortgage=finding.mortgage,
        mortgage_identified_by=finding.mortgage_identified_by,
        releases=finding.releases,
        borrower_mortgages=finding.borrower_mortgages,
        candidates=finding.candidates,
        notes=finding.notes,
    )
    cited: dict[str, RecordedInstrument] = {}
    for document in (
        ([finding.mortgage] if finding.mortgage else [])
        + [match.release for match in finding.releases + finding.candidates]
        + [
            document
            for owed in finding.borrower_mortgages
            for document in [owed.mortgage] + [match.release for match in owed.releases]
        ]
    ):
        cited.setdefault(document.number, document)
    citations = [
        SourceCitation(
            label=f"{document.document_type or document.kind.value} {document.instrument_number}",
            uri=document.detail_url,
            recording_reference=document.instrument_number,
            retrieved_at=retrieved_at,
        )
        for document in cited.values()
    ]
    status = (
        SourceResultStatus.NO_RESULTS
        if finding.status is ReleaseFindingStatus.MORTGAGE_NOT_FOUND
        else SourceResultStatus.SUCCEEDED
    )
    return SourceResult(
        source_id=descriptor.source_id,
        status=status,
        records=[record.model_dump(mode="json")],
        citations=citations,
        warnings=list(finding.notes),
        requires_human_review=True,
    )


# --------------------------------------------------------------- internals


async def _find_mortgage(
    index: RecorderIndex, query: MortgageReleaseQuery, notes: list[str]
) -> tuple[RecordedInstrument | None, MortgageIdentifiedBy | None]:
    if query.mortgage_instrument_number:
        how = MortgageIdentifiedBy.INSTRUMENT_NUMBER
        wanted = normalize_instrument_number(query.mortgage_instrument_number)
        hits = [
            document
            for document in await index.by_instrument(query.mortgage_instrument_number)
            if document.number == wanted
        ]
        if not hits:
            notes.append(
                f"No instrument {query.mortgage_instrument_number} is in the index. Check it "
                "against the commitment; it may be a book and page, or not yet indexed."
            )
    elif query.mortgage_book and query.mortgage_page:
        how = MortgageIdentifiedBy.BOOK_PAGE
        hits = await index.by_book_page(query.mortgage_book, query.mortgage_page)
        if not hits:
            notes.append(
                f"No instrument at book {query.mortgage_book}, page {query.mortgage_page} is in "
                "the index."
            )
    else:
        return None, None
    if not hits:
        return None, None
    mortgage = next((d for d in hits if d.kind is InstrumentKind.MORTGAGE), hits[0])
    if mortgage.kind is not InstrumentKind.MORTGAGE:
        notes.append(
            f"Instrument {mortgage.instrument_number} is indexed as "
            f"{mortgage.document_type or mortgage.kind.value}, not as a mortgage."
        )
    return mortgage, how


async def _borrower_mortgages(
    index: RecorderIndex, query: MortgageReleaseQuery, notes: list[str]
) -> list[BorrowerMortgage]:
    paid_off = query.paid_off_on
    if paid_off is None:
        notes.append(
            "Without the payoff date the borrower's mortgages cannot be narrowed to the one "
            "paid off, so releases naming the borrower are reported as candidates instead."
        )
        return []
    found: dict[str, RecordedInstrument] = {}
    released_since: set[str] = set()
    for borrower in query.borrower_names:
        for document in await index.by_party(borrower):
            recorded = document.recorded_on
            if document.kind in RELEASE_KINDS and recorded and recorded >= paid_off:
                # A release since the payoff points at the mortgage it discharges.
                released_since.update(
                    normalize_instrument_number(r.instrument_number) for r in document.references
                )
            if document.kind is not InstrumentKind.MORTGAGE or document.number in found:
                continue
            if not any(same_party(borrower, grantor) for grantor in document.grantors):
                continue
            if recorded and recorded >= paid_off:
                # Recorded at or after the payoff: a new loan, not the one paid off.
                continue
            found[document.number] = document
    recent = sorted(found.values(), key=lambda m: m.recorded_on or date.min, reverse=True)
    # The most recent, plus any older one a release since the payoff points at.
    # A common name matches other people's mortgages, which crowd out the
    # borrower's own; a release since the payoff picks theirs out.
    checked = recent[:MAX_BORROWER_MORTGAGES] + [
        m for m in recent[MAX_BORROWER_MORTGAGES:] if m.number in released_since
    ]
    owed: list[BorrowerMortgage] = []
    for mortgage in checked:
        linked = await _referenced_releases(index, mortgage)
        released_before = [
            match
            for match in linked
            if match.release.kind is InstrumentKind.RELEASE
            and match.release.recorded_on is not None
            and match.release.recorded_on < paid_off
        ]
        owed.append(
            BorrowerMortgage(
                mortgage=mortgage,
                open_at_payoff=not released_before,
                releases=[match for match in linked if match not in released_before],
            )
        )
    if not found:
        notes.append("No mortgage given by the borrower before the payoff is in the index.")
    elif len(found) > len(checked):
        notes.append(
            f"The borrower's name matches {len(found)} mortgages before the payoff; the "
            f"{len(checked)} most likely were checked. A common name matches other people's."
        )
    return owed


def _the_paid_off_mortgage(
    owed: list[BorrowerMortgage], query: MortgageReleaseQuery
) -> tuple[BorrowerMortgage | None, str]:
    """Which of the borrower's mortgages open at the payoff was paid off, and why.

    Old mortgages often look open only because their releases were recorded
    before the county linked documents, so being open is weak evidence on its
    own. Being released since the payoff is strong: that is what a payoff
    produces. The named lender is weaker still, because a payoff goes to
    whoever services the loan, not to the lender on the mortgage.
    """
    still_open = [entry for entry in owed if entry.open_at_payoff]
    released_since = [entry for entry in still_open if entry.released]
    releasing = {
        match.release.number
        for entry in released_since
        for match in entry.releases
        if match.release.kind is InstrumentKind.RELEASE
    }
    if len(released_since) > 1 and len(releasing) == 1:
        # One release discharging several linked mortgages, often a loan and
        # its modification: take the most recent of them.
        return released_since[0], "released, with others, by the one release since the payoff"
    to_lender = [
        entry
        for entry in still_open
        if any(
            same_party(lender, grantee)
            for lender in query.lender_names
            for grantee in entry.mortgage.grantees
        )
    ]
    if len(released_since) == 1:
        return released_since[0], "the only one of them released since the payoff"
    if len(to_lender) == 1:
        return to_lender[0], "the only one of them to the lender the payoff went to"
    if len(still_open) == 1:
        return still_open[0], "the only one still open on the payoff date"
    return None, ""


async def _referenced_releases(
    index: RecorderIndex, mortgage: RecordedInstrument
) -> list[ReleaseMatch]:
    matches: list[ReleaseMatch] = []
    for reference in mortgage.references:
        # A reference without a document type has to be looked up to know
        # what it is; one with a type that isn't a release can be skipped.
        if reference.document_type and reference.kind not in RELEASE_KINDS:
            continue
        wanted = normalize_instrument_number(reference.instrument_number)
        found = [
            d for d in await index.by_instrument(reference.instrument_number) if d.number == wanted
        ]
        release = found[0] if found else None
        if release is None and reference.kind in RELEASE_KINDS:
            # Listed on the mortgage but not returned by a lookup: report what
            # the reference itself says rather than drop it.
            release = RecordedInstrument(
                instrument_number=reference.instrument_number,
                document_type=reference.document_type,
                kind=reference.kind,
            )
        if release is None or release.kind not in RELEASE_KINDS:
            continue
        matches.append(
            ReleaseMatch(
                release=release,
                basis=ReleaseMatchBasis.INDEX_REFERENCE,
                explanation=(
                    f"The county's index links {release.document_type or 'release'} "
                    f"{release.instrument_number} to mortgage {mortgage.instrument_number}."
                ),
            )
        )
    return matches


async def _citing_releases(index: RecorderIndex, instrument_number: str) -> list[ReleaseMatch]:
    wanted = normalize_instrument_number(instrument_number)
    matches: list[ReleaseMatch] = []
    for document in await index.citing(instrument_number):
        if document.kind not in RELEASE_KINDS or document.number == wanted:
            continue
        if document.cites(instrument_number):
            basis = ReleaseMatchBasis.INDEX_REFERENCE
            explanation = (
                f"{document.document_type or 'Release'} {document.instrument_number} is linked "
                f"in the county's index to mortgage {instrument_number}."
            )
        else:
            basis = ReleaseMatchBasis.TEXT_REFERENCE
            explanation = (
                f"The text of {document.document_type or 'release'} {document.instrument_number} "
                f"cites instrument {instrument_number}."
            )
        matches.append(ReleaseMatch(release=document, basis=basis, explanation=explanation))
    return matches


async def _party_candidates(
    index: RecorderIndex,
    query: MortgageReleaseQuery,
    mortgage: RecordedInstrument | None,
    notes: list[str],
) -> list[ReleaseMatch]:
    lenders = list(query.lender_names) + (mortgage.grantees if mortgage else [])
    floor = query.paid_off_on or (mortgage.recorded_on if mortgage else None)
    if not lenders:
        notes.append(
            "No lender was given and no mortgage was found, so candidates are any release "
            "naming the borrower."
        )
    seen: set[str] = set()
    candidates: list[ReleaseMatch] = []
    for borrower in query.borrower_names:
        for document in await index.by_party(borrower, recorded_from=floor):
            if document.kind not in RELEASE_KINDS or document.number in seen:
                continue
            parties = document.grantors + document.grantees
            if not any(same_party(borrower, party) for party in parties):
                continue
            lender = next(
                (party for party in parties for name in lenders if same_party(name, party)),
                None,
            )
            if lenders and lender is None:
                continue
            if (
                mortgage is not None
                and document.references
                and not document.cites(mortgage.instrument_number)
            ):
                # The index links this release to some other instrument.
                continue
            seen.add(document.number)
            candidates.append(
                ReleaseMatch(
                    release=document,
                    basis=ReleaseMatchBasis.PARTY_MATCH,
                    explanation=(
                        f"{document.document_type or 'Release'} {document.instrument_number} names "
                        f"{borrower}"
                        + (f" and {lender}" if lender else "")
                        + (f", recorded on or after {floor.isoformat()}" if floor else "")
                        + ". Nothing in the index ties it to this mortgage."
                    ),
                )
            )
    return candidates


def _status(
    mortgage: RecordedInstrument | None,
    releases: list[ReleaseMatch],
    candidates: list[ReleaseMatch],
    borrower_mortgages: list[BorrowerMortgage],
) -> ReleaseFindingStatus:
    if any(match.release.kind is InstrumentKind.RELEASE for match in releases):
        return ReleaseFindingStatus.RELEASED
    if releases:
        return ReleaseFindingStatus.PARTIALLY_RELEASED
    if candidates:
        return ReleaseFindingStatus.CANDIDATES_ONLY
    if mortgage is not None:
        return ReleaseFindingStatus.NOT_RELEASED
    if any(entry.open_at_payoff for entry in borrower_mortgages):
        return ReleaseFindingStatus.NOT_RELEASED
    return ReleaseFindingStatus.MORTGAGE_NOT_FOUND


def _status_notes(
    status: ReleaseFindingStatus,
    query: MortgageReleaseQuery,
    mortgage: RecordedInstrument | None,
    releases: list[ReleaseMatch],
    borrower_mortgages: list[BorrowerMortgage],
) -> list[str]:
    notes: list[str] = []
    still_open = [entry for entry in borrower_mortgages if entry.open_at_payoff]
    if mortgage is None and len(still_open) > 1:
        released = [e.mortgage.instrument_number for e in still_open if e.released]
        notes.append(
            f"The borrower had {len(still_open)} mortgages that look open on the payoff date "
            "(an old release may simply not be linked), so which was paid off can't be told "
            "from the index. "
            + (
                f"Released since: {', '.join(released)}."
                if released
                else "None of them shows a release since the payoff."
            )
        )
    if status is ReleaseFindingStatus.NOT_RELEASED and mortgage is not None:
        notes.append(
            f"No release of mortgage {mortgage.instrument_number} is in the index. A recent "
            "recording can take days or weeks to appear."
        )
    if status is ReleaseFindingStatus.CANDIDATES_ONLY:
        notes.append(
            "These releases name the same parties, but nothing in the index ties them to this "
            "mortgage. Check each against the mortgage before relying on it."
        )
    if query.paid_off_on:
        for match in releases:
            recorded = match.release.recorded_on
            if recorded and recorded < query.paid_off_on:
                notes.append(
                    f"{match.release.instrument_number} was recorded on {recorded.isoformat()}, "
                    f"before the payoff on {query.paid_off_on.isoformat()}. It may release an "
                    "earlier loan; check the image."
                )
    return notes

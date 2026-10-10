"""Recorded instruments, and whether a mortgage has been released of record.

County recorders run a handful of vendor platforms, and each describes a
document in its own vocabulary: Cuyahoga writes ``RELS - RELEASE SATISFACTION``
where Stark writes ``MORTGAGE RELEASE``. These models are the shape every
recorder connector maps into, so a caller asking "was this mortgage released?"
gets one answer whichever county it asked.

A release found here is a reading of the county's index, not a title opinion.
Every result is marked for human review.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from title_mcp.domain.models import Jurisdiction


class InstrumentKind(StrEnum):
    DEED = "deed"
    MORTGAGE = "mortgage"
    RELEASE = "release"
    PARTIAL_RELEASE = "partial_release"
    ASSIGNMENT = "assignment"
    MODIFICATION = "modification"
    OTHER = "other"


#: Abbreviations county indexes use, by the word they stand for.
_TYPE_WORDS = {
    "REL": "RELEASE",
    "RL": "RELEASE",
    "RELEA": "RELEASE",
    "RELEAS": "RELEASE",
    "PT": "PARTIAL",
    "PART": "PARTIAL",
    "ASSIGN": "ASSIGNMENT",
    "ASSIGNMT": "ASSIGNMENT",
    "ASSN": "ASSIGNMENT",
    "ASN": "ASSIGNMENT",
    "ASMT": "ASSIGNMENT",
    "ASGN": "ASSIGNMENT",
    "MTG": "MORTGAGE",
    "MTGE": "MORTGAGE",
    "MORT": "MORTGAGE",
    "MORTG": "MORTGAGE",
    "MODIF": "MODIFICATION",
    "MODIFIC": "MODIFICATION",
}

#: The only words a release of a mortgage is described with, besides the
#: release itself. A release naming anything else (a lease, a tax lien, a right
#: of way, an assignment) releases something else.
_MORTGAGE_RELEASE_WORDS = frozenset(
    {
        "RELEASE",
        "PARTIAL",
        "MORTGAGE",
        "OF",
        "THE",
        "AND",
        "N",
        "C",
        "NC",
        "NO",
        "CHARGE",
        "COURT",
        "JOURNAL",
        "AMEND",
        "AMENDED",
        "AMENDMENT",
        "INDENTURE",
        "INDENTR",
        "INDE",
        "TORRENS",
        "FULL",
    }
)

#: The words a mortgage assignment is described with, besides the assignment.
_MORTGAGE_ASSIGNMENT_WORDS = frozenset({"ASSIGNMENT", "MORTGAGE", "PARTIAL", "OF", "N", "C"})


def classify_instrument(document_type: str) -> InstrumentKind:
    """What a county's document type description means.

    Counties describe the same instrument many ways: ``RELS - RELEASE
    SATISFACTION``, ``MORTGAGE RELEASE``, ``RELEASE MORTGAGE``, and in
    abbreviation ``PT REL MORTGAGE``. The description is read as words, with
    the county's code prefix set aside and abbreviations expanded, so order
    and abbreviation don't matter. A release is a mortgage's only when every
    other word in it could describe one: county indexes also hold releases of
    leases, tax liens, rights of way and assignments, which say so.
    """
    description = (document_type or "").upper()
    if " - " in description:
        description = description.split(" - ", 1)[1]
    words = {_TYPE_WORDS.get(word, word) for word in re.findall(r"[A-Z]+", description)}
    if words & {"RESCISSION", "REVOKE", "RVK"}:
        return InstrumentKind.OTHER
    releasing = {
        word
        for word in words
        if word == "RELEASE" or word.startswith(("SATISF", "DISCHARG", "CANCEL"))
    }
    if releasing and (releasing != {"CANCELLATION"} or "MORTGAGE" in words):
        if not words - releasing - _MORTGAGE_RELEASE_WORDS:
            return InstrumentKind.PARTIAL_RELEASE if "PARTIAL" in words else InstrumentKind.RELEASE
        if "MODIFICATION" in words or "SUBORDINATION" in words:
            return InstrumentKind.MODIFICATION
        return InstrumentKind.OTHER
    if "MODIFICATION" in words or any(word.startswith("SUBORDINAT") for word in words):
        return InstrumentKind.MODIFICATION
    if "ASSIGNMENT" in words:
        if words <= _MORTGAGE_ASSIGNMENT_WORDS:
            return InstrumentKind.ASSIGNMENT
        return InstrumentKind.OTHER
    if "MORTGAGE" in words:
        return InstrumentKind.MORTGAGE
    if "DEED" in words:
        return InstrumentKind.DEED
    return InstrumentKind.OTHER


def normalize_instrument_number(value: str | None) -> str:
    """An instrument number without the punctuation counties and title plants add."""
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())


#: Words that say nothing about which lender a name belongs to.
_NAME_NOISE = frozenset(
    {"THE", "OF", "AND", "CO", "INC", "LLC", "NA", "N", "A", "FSB", "CORP", "CORPORATION"}
)

#: Indexes abbreviate freely: ``HUNTINGTON NATL BK ETAL`` is Huntington National Bank.
_ABBREVIATIONS = {"NATL": "NATIONAL", "BK": "BANK", "MTG": "MORTGAGE", "FED": "FEDERAL"}


def party_key(name: str) -> str:
    """A party's name reduced to its significant words, abbreviations expanded."""
    upper = re.sub(r"[^A-Z ]", " ", (name or "").upper())
    words = [_ABBREVIATIONS.get(word, word) for word in upper.split()]
    return " ".join(word for word in words if word not in _NAME_NOISE)


#: Words that end a business's name rather than start a qualifier.
_ENTITY_WORDS = frozenset(
    {"LLC", "L", "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LP", "LLP", "TRUST", "BANK"}
)

#: Where the name a deed or mortgage gives a person stops and the description
#: of them starts: "JANE DOE, AS TRUSTEE OF ...", "JOHN DOE AKA JACK DOE".
_QUALIFIER = re.compile(r"\b(AS|TRUSTEES?|TR|ET ?AL|AKA|FKA|NKA|SUCCESSOR|INDIVIDUALLY)\b")


def index_search_name(name: str) -> str:
    """A party's name as an index search wants it.

    A mortgage names its borrowers the way the deed did: "Jane D. Doe, a
    widow", "John Doe, as Trustee of the Doe Family Trust". Recorder searches
    match words, so the qualifier, the punctuation and single-letter initials
    only stop a match. A business keeps its suffix: "ACME HOMES, LLC".
    """
    upper = (name or "").upper()
    head, _, rest = upper.partition(",")
    after = re.sub(r"[^A-Z ]", " ", rest).split()
    if after and after[0] in _ENTITY_WORDS:
        head = f"{head} {after[0]}"
    head = _QUALIFIER.split(head)[0]
    words = re.sub(r"[^A-Z0-9& ]", " ", head).split()
    if not any(word in _ENTITY_WORDS for word in words):
        words = [word for word in words if len(word) > 1]
    return " ".join(words)


def same_party(left: str, right: str) -> bool:
    """Whether two index names plausibly name the same party.

    Either the first two significant words agree, which tells lenders apart
    without requiring the index to spell a name the same way twice, or every
    word of the shorter name appears in the longer, which matches a person
    whatever order the names are in: ``JANE DOE`` and ``DOE JANE M``.
    Initials are ignored in the second test.
    """
    a, b = party_key(left).split(), party_key(right).split()
    if not a or not b:
        return False
    if a[:2] == b[:2]:
        return True
    shorter, longer = sorted(([w for w in a if len(w) > 1], [w for w in b if len(w) > 1]), key=len)
    return len(shorter) >= 2 and set(shorter) <= set(longer)


class InstrumentReference(BaseModel):
    """Another instrument that the county's index links to this one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_number: str
    document_type: str = ""
    kind: InstrumentKind = InstrumentKind.OTHER


class RecordedInstrument(BaseModel):
    """One recorded document, as a county index describes it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_number: str = ""
    recorded_on: date | None = None
    document_type: str = ""
    document_type_code: str = ""
    kind: InstrumentKind = InstrumentKind.OTHER
    grantors: list[str] = Field(default_factory=list)
    grantees: list[str] = Field(default_factory=list)
    book: str = ""
    page: str = ""
    legal_description: str = ""
    references: list[InstrumentReference] = Field(default_factory=list)
    detail_url: str | None = None
    #: Text read off the document's image, where the county provides it.
    #: Kept so a caller can see why a text match was made; never returned whole.
    text_excerpt: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def number(self) -> str:
        return normalize_instrument_number(self.instrument_number)

    def cites(self, instrument_number: str) -> bool:
        """Whether this document's index entry links to the given instrument."""
        wanted = normalize_instrument_number(instrument_number)
        return any(
            normalize_instrument_number(r.instrument_number) == wanted for r in self.references
        )


class MortgageReleaseQuery(BaseModel):
    """The mortgage to look for a release of.

    The mortgage's instrument number (or book and page) is what makes an
    answer exact. Borrower and lender names are a fallback, and anything found
    through them alone is a candidate for review, not an answer.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    mortgage_instrument_number: str | None = None
    mortgage_book: str | None = None
    mortgage_page: str | None = None
    borrower_names: list[str] = Field(default_factory=list)
    lender_names: list[str] = Field(default_factory=list)
    #: When the loan was paid off. A release recorded before this is noted.
    paid_off_on: date | None = None

    @field_validator("borrower_names", "lender_names")
    @classmethod
    def _names(cls, value: list[str]) -> list[str]:
        return [name.strip().upper() for name in value if name and name.strip()]

    @model_validator(mode="after")
    def _something_to_look_for(self) -> MortgageReleaseQuery:
        if not (
            self.mortgage_instrument_number
            or (self.mortgage_book and self.mortgage_page)
            or self.borrower_names
        ):
            raise ValueError(
                "Give the mortgage's instrument number, its book and page, or the borrowers' "
                "names. A county index cannot be searched by street address."
            )
        return self


class ReleaseMatchBasis(StrEnum):
    #: The county's own index links the release to the mortgage.
    INDEX_REFERENCE = "index_reference"
    #: The release's text cites the mortgage's instrument number.
    TEXT_REFERENCE = "text_reference"
    #: A release between the same lender and borrower, recorded after the payoff.
    PARTY_MATCH = "party_match"


class ReleaseMatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    release: RecordedInstrument
    basis: ReleaseMatchBasis
    explanation: str = ""


class ReleaseFindingStatus(StrEnum):
    #: A release of the whole mortgage is of record.
    RELEASED = "released"
    #: Only partial releases are of record.
    PARTIALLY_RELEASED = "partially_released"
    #: Nothing ties a release to the mortgage, but name matches are worth a look.
    CANDIDATES_ONLY = "candidates_only"
    #: The mortgage is in the index and no release of it is.
    NOT_RELEASED = "not_released"
    #: The mortgage itself could not be found, and no candidate release was.
    MORTGAGE_NOT_FOUND = "mortgage_not_found"


class MortgageIdentifiedBy(StrEnum):
    INSTRUMENT_NUMBER = "instrument_number"
    BOOK_PAGE = "book_page"
    #: The borrower's only mortgage still open on the payoff date.
    PARTIES = "parties"


class BorrowerMortgage(BaseModel):
    """A mortgage the borrower gave before the payoff, and what released it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mortgage: RecordedInstrument
    #: No full release of it was recorded before the payoff date.
    open_at_payoff: bool
    #: Releases linked to it and not recorded before the payoff.
    releases: list[ReleaseMatch] = Field(default_factory=list)

    @property
    def released(self) -> bool:
        return any(match.release.kind is InstrumentKind.RELEASE for match in self.releases)


class RecorderSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    source_name: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None


class MortgageReleaseRecord(BaseModel):
    """Whether one mortgage has been released of record, and on what basis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.mortgage_release_search"
    schema_version: str = "1.0"
    record_type: Literal["mortgage_release_search"] = "mortgage_release_search"
    source: RecorderSource
    jurisdiction: Jurisdiction
    query: MortgageReleaseQuery
    status: ReleaseFindingStatus
    mortgage: RecordedInstrument | None = None
    mortgage_identified_by: MortgageIdentifiedBy | None = None
    releases: list[ReleaseMatch] = Field(default_factory=list)
    #: Without the mortgage's number: every mortgage the borrower gave before
    #: the payoff, and whether each was open then and released since.
    borrower_mortgages: list[BorrowerMortgage] = Field(default_factory=list)
    candidates: list[ReleaseMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)

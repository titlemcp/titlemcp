"""Turning an index search into a chain for one parcel.

A name search returns every document naming that party anywhere in the county.
For the search that motivated this module, one owner returned twenty-one
documents across three unrelated properties, two of which sat in subdivisions
with nearly the same name: ``FRANK S WAGENHALS ET AL AMENDED SUBD`` and
``WAGENHALS ET AL AMENDED SUBD``. Matching on the subdivision picks the wrong
chain and reports the wrong lender, confidently.

What makes the answer right is that the county writes the parcel number into
the legal description of each instrument. That is the join. Everything here is
built on it.

Two more things a naive reading gets wrong, both encountered on real records:

- A deed is only an acquisition if the owner is the **grantee**. The same owner
  had a deed a fortnight after buying, where they were the grantor: a different
  property, sold, not bought.
- The lender is not the first name on a mortgage. MERS appears as nominee on
  most modern instruments and is not who a payoff comes from.

Nothing here decides anything. It assembles what the record says and marks it
for review, because an open lien is a title-impacting fact.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from titlemcp_us_oh_franklin_recorder.client import RecorderDocument


class InstrumentKind(StrEnum):
    DEED = "deed"
    MORTGAGE = "mortgage"
    RELEASE = "release"
    ASSIGNMENT = "assignment"
    OTHER = "other"


#: Document type strings the county uses, mapped to what they mean. Matched as
#: substrings because the index is not consistent about suffixes.
TYPE_PATTERNS: tuple[tuple[str, InstrumentKind], ...] = (
    ("RELEASE", InstrumentKind.RELEASE),
    ("SATISFACTION", InstrumentKind.RELEASE),
    ("ASSIGN", InstrumentKind.ASSIGNMENT),
    ("MORTGAGE", InstrumentKind.MORTGAGE),
    ("DEED", InstrumentKind.DEED),
)

#: Names that appear on a mortgage without being the lender. MERS is a nominee
#: holding legal title for whoever owns the note; a payoff never comes from it.
NOMINEE_PATTERNS = ("MERS", "MORTGAGE ELECTRONIC REGISTRATION")

#: Parcel numbers as the legal descriptions write them: 030-000526-00, and
#: sometimes without the trailing pair.
PARCEL_IN_LEGAL = re.compile(r"(\d{3})-(\d{6})(?:-(\d{2}))?")


class ChainDocument(BaseModel):
    """A recorded instrument, classified and dated."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: InstrumentKind
    instrument_number: str
    recorded_on: date | None = None
    recorded_date: str = ""
    document_type: str = ""
    grantors: list[str] = Field(default_factory=list)
    grantees: list[str] = Field(default_factory=list)
    legal_description: str = ""

    @property
    def lenders(self) -> list[str]:
        """Grantees that are not nominees. On a mortgage, who to ask."""
        return [name for name in self.grantees if not _is_nominee(name)]

    @property
    def nominees(self) -> list[str]:
        return [name for name in self.grantees if _is_nominee(name)]


class OpenLien(BaseModel):
    """A mortgage with no release of record. Not a legal opinion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_number: str
    recorded_date: str
    lenders: list[str] = Field(default_factory=list)
    nominees: list[str] = Field(default_factory=list)
    borrowers: list[str] = Field(default_factory=list)
    is_purchase_money: bool = False
    basis: str = ""


class ParcelChain(BaseModel):
    """What the record shows for one parcel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str
    documents_searched: int = 0
    documents_on_parcel: int = 0
    acquisition: ChainDocument | None = None
    open_liens: list[OpenLien] = Field(default_factory=list)
    released: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    notes: list[str] = Field(default_factory=list)


def normalize_parcel(parcel_id: str) -> str:
    """The digits of a parcel number, however it was punctuated."""
    return re.sub(r"\D", "", parcel_id or "")


def classify(document_type: str) -> InstrumentKind:
    upper = (document_type or "").upper()
    for pattern, kind in TYPE_PATTERNS:
        if pattern in upper:
            return kind
    return InstrumentKind.OTHER


def parcels_in(legal_description: str) -> set[str]:
    """Every parcel number a legal description cites."""
    found = set()
    for match in PARCEL_IN_LEGAL.finditer(legal_description or ""):
        found.add(normalize_parcel("".join(part for part in match.groups() if part)))
    return found


def on_parcel(document: RecorderDocument, parcel_id: str) -> bool:
    """Whether this instrument concerns the parcel.

    Compared on the leading nine digits, because the index writes the trailing
    pair inconsistently: ``030-000526-00`` and ``030-000526`` are one parcel.
    """
    wanted = normalize_parcel(parcel_id)[:9]
    if not wanted:
        return False
    return any(found[:9] == wanted for found in parcels_in(document.legal_description))


def build(
    *,
    parcel_id: str,
    owner_name: str,
    documents: list[RecorderDocument],
) -> ParcelChain:
    """Assemble the chain for one parcel out of a countywide name search."""
    scoped = [document for document in documents if on_parcel(document, parcel_id)]
    chain = [
        ChainDocument(
            kind=classify(document.document_type),
            instrument_number=document.instrument_number,
            recorded_on=_parse_date(document.recorded_date),
            recorded_date=document.recorded_date,
            document_type=document.document_type,
            grantors=document.grantors,
            grantees=document.grantees,
            legal_description=document.legal_description,
        )
        for document in scoped
    ]
    chain.sort(key=lambda item: (item.recorded_on or date.min, item.instrument_number))

    result = ParcelChain(
        parcel_id=parcel_id,
        documents_searched=len(documents),
        documents_on_parcel=len(scoped),
    )
    if not scoped:
        result.notes.append(
            f"No instrument naming this party cites parcel {parcel_id}. The party may hold "
            "it under another name, or the search term may be wrong."
        )
        return result

    surname = _surname(owner_name)
    acquisition = next(
        (
            document
            for document in reversed(chain)
            if document.kind is InstrumentKind.DEED
            and any(surname in name for name in document.grantees)
        ),
        None,
    )
    result.acquisition = acquisition
    if acquisition is None:
        result.notes.append(
            "No deed on this parcel names the party as grantee, so the acquisition could "
            "not be identified. Mortgages below are reported without one."
        )

    floor = acquisition.recorded_on if acquisition and acquisition.recorded_on else date.min
    mortgages = [
        document
        for document in chain
        if document.kind is InstrumentKind.MORTGAGE
        and (document.recorded_on or date.min) >= floor
    ]
    releases = [document for document in chain if document.kind is InstrumentKind.RELEASE]

    for mortgage in mortgages:
        release = _release_for(mortgage, releases)
        if release is not None:
            result.released.append(mortgage.instrument_number)
            continue
        result.open_liens.append(
            OpenLien(
                instrument_number=mortgage.instrument_number,
                recorded_date=mortgage.recorded_date,
                lenders=mortgage.lenders,
                nominees=mortgage.nominees,
                borrowers=mortgage.grantors,
                is_purchase_money=_follows(acquisition, mortgage),
                basis="No release of this mortgage appears in the searched index.",
            )
        )

    if not mortgages:
        result.notes.append("No mortgage on this parcel after the acquisition.")
    return result


# --------------------------------------------------------------- internals


def _is_nominee(name: str) -> bool:
    upper = name.upper()
    return any(pattern in upper for pattern in NOMINEE_PATTERNS)


def _surname(owner_name: str) -> str:
    """County indexes are surname-first, so the first token is the family name."""
    parts = [part for part in (owner_name or "").upper().split() if part]
    return parts[0] if parts else ""


def _parse_date(value: str) -> date | None:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%b-%d-%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except (ValueError, AttributeError):
            continue
    return None


def _release_for(mortgage: ChainDocument, releases: list[ChainDocument]) -> ChainDocument | None:
    """A later release naming the same lender.

    Matched on the lender rather than on an instrument reference, because the
    index does not carry the released instrument number. That makes this a
    reading of the index, not a title opinion, which is why the result is
    marked for review.
    """
    for release in releases:
        if (release.recorded_on or date.min) < (mortgage.recorded_on or date.min):
            continue
        for lender in mortgage.lenders or mortgage.grantees:
            key = _match_key(lender)
            if key and any(key in _match_key(name) for name in release.grantees):
                return release
    return None


def _match_key(name: str) -> str:
    """Enough of a lender's name to match on, without matching everything."""
    upper = re.sub(r"[^A-Z ]", "", (name or "").upper())
    words = [word for word in upper.split() if word not in {"THE", "OF", "CO", "INC", "NA"}]
    return " ".join(words[:2])


def _follows(deed: ChainDocument | None, mortgage: ChainDocument) -> bool:
    """A purchase-money mortgage is recorded immediately after its deed."""
    if deed is None:
        return False
    try:
        return int(mortgage.instrument_number) == int(deed.instrument_number) + 1
    except (TypeError, ValueError):
        return False

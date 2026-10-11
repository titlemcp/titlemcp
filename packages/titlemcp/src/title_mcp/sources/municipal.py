"""Finding the offices to ask about a parcel's municipal liens, permits and code cases.

A directory connector holds one entry per government; shaping the answer happens
here, so every state's answer reads the same. A parcel inside a city deals with
the city's offices for most things and the county's for countywide services, so
the answer carries both entries.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.municipal import (
    MunicipalDirectorySource,
    MunicipalLienDirectoryRecord,
    MunicipalOffice,
)
from title_mcp.sources.base import (
    SourceCitation,
    SourceDescriptor,
    SourceResult,
    SourceResultStatus,
)

#: Entries read longer ago than this are called out: a fee or process may have changed.
STALE_AFTER_DAYS = 365


@runtime_checkable
class MunicipalDirectory(Protocol):
    """A directory of the local governments in a state, or part of one."""

    source_id: str
    descriptor: SourceDescriptor

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        """Whether the directory covers the jurisdiction."""
        ...

    async def find_offices(self, jurisdiction: Jurisdiction) -> SourceResult:
        """The county's entry, and the municipality's when one is given."""
        ...


def municipal_directory_result(
    *,
    descriptor: SourceDescriptor,
    jurisdiction: Jurisdiction,
    municipality: MunicipalOffice | None,
    county: MunicipalOffice | None,
    coverage: str | None = None,
    today: date | None = None,
) -> SourceResult:
    """The directory's entries for a place, as a canonical record."""
    today = today or date.today()
    offices = [office for office in (municipality, county) if office is not None]
    notes = _notes(jurisdiction, municipality, county, coverage, today)
    record = MunicipalLienDirectoryRecord(
        source=MunicipalDirectorySource(
            source_id=descriptor.source_id,
            source_name=descriptor.name,
            checked_on=min((office.checked_on for office in offices), default=None),
        ),
        jurisdiction=jurisdiction,
        municipality=municipality,
        county=county,
        notes=notes,
    )
    if not offices:
        status = SourceResultStatus.NO_RESULTS
    elif jurisdiction.municipality and municipality is None:
        status = SourceResultStatus.PARTIAL
    else:
        status = SourceResultStatus.SUCCEEDED
    return SourceResult(
        source_id=descriptor.source_id,
        status=status,
        records=[record.model_dump(mode="json")],
        citations=_citations(offices),
        warnings=notes,
        requires_human_review=True,
    )


def _notes(
    jurisdiction: Jurisdiction,
    municipality: MunicipalOffice | None,
    county: MunicipalOffice | None,
    coverage: str | None,
    today: date,
) -> list[str]:
    notes: list[str] = []
    if jurisdiction.municipality and municipality is None:
        notes.append(
            f"The directory has no entry for {jurisdiction.municipality}; its own offices "
            "issue its lien letter." + (f" The directory covers {coverage}." if coverage else "")
        )
    if county is None:
        notes.append(f"The directory has no entry for {jurisdiction.county}.")
    elif municipality is not None:
        notes.append(
            f"{county.name}'s entry is for the county's own offices: the unincorporated "
            "area and countywide services."
        )
    else:
        notes.append(
            "For a parcel inside a city, give the municipality: the city's own offices "
            "issue its lien letter."
        )
    notes.append(
        "An address's postal city isn't always the municipality. Confirm the parcel's "
        "municipality or taxing district on the property appraiser's record."
    )
    for office in (municipality, county):
        if office is not None and (today - office.checked_on).days > STALE_AFTER_DAYS:
            notes.append(
                f"{office.name}'s entry was read on {office.checked_on.isoformat()}; confirm "
                "the fee and process on its pages before ordering."
            )
    return notes


def _citations(offices: list[MunicipalOffice]) -> list[SourceCitation]:
    citations: list[SourceCitation] = []
    for office in offices:
        uri = office.lien_letter.source_url or office.lien_letter.request_url or office.website
        if uri:
            citations.append(
                SourceCitation(
                    label=f"{office.name}, lien search",
                    uri=uri,
                    retrieved_at=office.checked_on.isoformat(),
                )
            )
    return citations

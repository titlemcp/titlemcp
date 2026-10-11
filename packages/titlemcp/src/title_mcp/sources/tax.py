"""Reading a parcel's property tax status from the collector's own record.

Each tax connector reads its collector's record into a ``TaxParcel``; judging
it and shaping the answer happen here, so every county's answer reads the same.
How current the answer is depends on the collector: some publish daily, some
quarterly. The record carries the data's date, and an old one is called out.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.tax import (
    PropertyTaxQuery,
    PropertyTaxStatusRecord,
    TaxParcel,
    TaxSource,
    TaxStatus,
    tax_status,
    total_balance,
)
from title_mcp.sources.base import (
    SourceCitation,
    SourceDescriptor,
    SourceResult,
    SourceResultStatus,
)

#: Older data than this is called out: a payment since then wouldn't show.
STALE_AFTER_DAYS = 7


@runtime_checkable
class PropertyTaxSource(Protocol):
    """A tax connector that can read one parcel's tax status."""

    source_id: str
    descriptor: SourceDescriptor

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        """Whether this connector covers the jurisdiction."""
        ...

    async def find_tax_status(
        self, jurisdiction: Jurisdiction, query: PropertyTaxQuery
    ) -> SourceResult:
        """Read the parcel's tax status."""
        ...


def tax_source_result(
    *,
    descriptor: SourceDescriptor,
    jurisdiction: Jurisdiction,
    query: PropertyTaxQuery,
    parcel: TaxParcel | None,
    refreshed: str | None = None,
    source_url: str | None = None,
    today: date | None = None,
) -> SourceResult:
    """The parcel's status as a canonical record, with the data's age noted."""
    today = today or date.today()
    retrieved_at = datetime.now(UTC).isoformat()
    source = TaxSource(
        source_id=descriptor.source_id,
        source_name=descriptor.name,
        source_url=source_url or descriptor.base_url,
        retrieved_at=retrieved_at,
        data_as_of=parcel.data_as_of if parcel else None,
        refreshed=refreshed,
    )
    if parcel is None:
        record = PropertyTaxStatusRecord(
            source=source,
            jurisdiction=jurisdiction,
            query=query,
            status=TaxStatus.PARCEL_NOT_FOUND,
            notes=[f"The collector's record has no parcel {query.parcel_id}."],
        )
        return SourceResult(
            source_id=descriptor.source_id,
            status=SourceResultStatus.NO_RESULTS,
            records=[record.model_dump(mode="json")],
            warnings=list(record.notes),
            requires_human_review=True,
        )

    status = tax_status(parcel, today)
    notes = _notes(status, parcel, today)
    record = PropertyTaxStatusRecord(
        source=source,
        jurisdiction=jurisdiction,
        query=query,
        status=status,
        parcel_id=parcel.parcel_id,
        taxpayer_name=parcel.taxpayer_name,
        property_address=parcel.property_address,
        collector=parcel.collector,
        years=parcel.years,
        other_charges=parcel.other_charges,
        total_balance=total_balance(parcel),
        notes=notes,
        source_specific=parcel.raw,
    )
    return SourceResult(
        source_id=descriptor.source_id,
        status=SourceResultStatus.SUCCEEDED,
        records=[record.model_dump(mode="json")],
        citations=[
            SourceCitation(
                label=f"{descriptor.name} parcel {parcel.parcel_id}",
                uri=source.source_url,
                retrieved_at=retrieved_at,
            )
        ],
        warnings=notes,
        requires_human_review=True,
    )


def _notes(status: TaxStatus, parcel: TaxParcel, today: date) -> list[str]:
    notes = list(parcel.notes)
    if parcel.data_as_of is None:
        notes.append(
            "The collector doesn't say when this data was extracted. Confirm it with the "
            "collector before closing."
        )
    elif (today - parcel.data_as_of).days > STALE_AFTER_DAYS:
        notes.append(
            f"The collector's data is as of {parcel.data_as_of.isoformat()}, "
            f"{(today - parcel.data_as_of).days} days ago; a payment since then isn't shown."
        )
    if status is TaxStatus.PAST_DUE:
        notes.append(
            "An amount is owed past its due date or on an earlier year. Get the payoff, with "
            "penalties and interest to the closing date, from the collector."
        )
    elif status is TaxStatus.DUE:
        notes.append("Tax is owed but not yet past due.")
    elif status is TaxStatus.UNKNOWN:
        notes.append("The collector's record shows no balances, so paid or owed can't be told.")
    return notes

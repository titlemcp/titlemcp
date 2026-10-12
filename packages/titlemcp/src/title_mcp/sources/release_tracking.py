"""Tracking a paid-off mortgage's release: the county's index, read against the state's deadline.

The release search is the county recorder connector's; the deadline is the
state's statute. With no connector for the county, the answer is the deadline
alone, so the release can be checked by hand on time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import MortgageReleaseQuery, MortgageReleaseRecord
from title_mcp.domain.release_deadlines import deadline_for
from title_mcp.domain.release_tracking import track_release
from title_mcp.sources.base import SourceCitation, SourceResult, SourceResultStatus
from title_mcp.sources.releases import MortgageReleaseSource

SOURCE_ID = "release-tracking"


async def release_tracking_result(
    *,
    connector: MortgageReleaseSource | None,
    jurisdiction: Jurisdiction,
    query: MortgageReleaseQuery,
    paid_off_on: date,
    as_of: date,
    requested_on: date | None = None,
) -> SourceResult:
    """Where the release stands, as a ``title_mcp.release_tracking_status`` record."""
    warnings: list[str] = []
    citations: list[SourceCitation] = []
    release_search: MortgageReleaseRecord | None = None
    if connector is None:
        warnings.append(
            f"No installed recorder connector checks releases for {jurisdiction.county}, "
            f"{jurisdiction.state}; only the deadline is given."
        )
    else:
        result = await connector.find_release(jurisdiction, query)
        citations.extend(result.citations)
        if result.records:
            release_search = MortgageReleaseRecord.model_validate(result.records[0])
        else:
            warnings.extend(result.warnings)
            warnings.append(
                f"The county's index couldn't be read ({result.status.value}); only the "
                "deadline is given."
            )

    deadline = deadline_for(jurisdiction.state)
    record = track_release(
        jurisdiction=jurisdiction,
        query=query,
        paid_off_on=paid_off_on,
        as_of=as_of,
        deadline=deadline,
        release_search=release_search,
        requested_on=requested_on,
    )
    if deadline is not None:
        citations.append(
            SourceCitation(
                label=deadline.citation,
                uri=deadline.url,
                retrieved_at=datetime.now(UTC).isoformat(),
            )
        )
    return SourceResult(
        source_id=SOURCE_ID,
        status=SourceResultStatus.SUCCEEDED if release_search else SourceResultStatus.PARTIAL,
        records=[record.model_dump(mode="json")],
        citations=citations,
        warnings=warnings + record.notes,
        requires_human_review=True,
    )

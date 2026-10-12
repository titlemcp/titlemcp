"""A paid-off mortgage's release, checked against the deadline the state sets for it.

Every state but a few gives the lender a deadline to release a mortgage once
it is paid, and most give the borrower a remedy when it is missed. To track a
release is to check the county's index against that clock until the release
shows up. This module holds the clock: each state's deadline as its statute
sets it (``title_mcp.domain.release_deadlines``), and a release finding judged
against it.

The statutes differ in ways that decide what the index can show:
- In some states the clock starts at payoff; in others only with the owner's
  written request, so there is no deadline until a request is made.
- Some require the lender to record the release. Others let it deliver the
  release to the borrower instead, so an empty index doesn't show it was late.
- Most let a title insurer or attorney clear the lien without the lender, by
  recording an affidavit or certificate after notice.

Nothing here decides that a lien is gone or that a remedy applies. It reports
what the index shows and what the statute says, and marks it for review.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import (
    InstrumentKind,
    MortgageReleaseQuery,
    MortgageReleaseRecord,
    RecorderSource,
    ReleaseFindingStatus,
)

#: How often to look again while a release is awaited or overdue.
RECHECK_EVERY_DAYS = 7


class ClockStart(StrEnum):
    #: The deadline counts from the payoff.
    PAYOFF = "payoff"
    #: The deadline counts only from the owner's written request after payoff.
    REQUEST = "request"


class ReleaseDeadline(BaseModel):
    """How long a state's statute gives the lender to release a paid-off mortgage."""

    model_config = ConfigDict(str_strip_whitespace=True)

    state: str = Field(min_length=2, max_length=2)
    #: The period, in calendar days or, where the statute says so, months.
    days: int | None = Field(default=None, gt=0)
    months: int | None = Field(default=None, gt=0)
    clock_start: ClockStart = ClockStart.PAYOFF
    #: Whether the duty is to record the release. Where the lender may deliver it
    #: to the borrower instead, an empty index doesn't show it was late.
    lender_records: bool = True
    #: What starts the clock, in the statute's terms.
    trigger: str
    #: Who must do what.
    duty: str
    citation: str
    url: str
    #: What the borrower may recover when the deadline is missed, and how.
    remedy: str | None = None
    #: Whether the remedy needs a written demand first, and how long it then allows.
    demand_required: bool | None = None
    demand_wait_days: int | None = None
    #: A way for someone other than the lender, such as a title insurer or
    #: attorney, to clear the lien.
    alternative_release: str | None = None
    alternative_citation: str | None = None
    #: Other deadlines or conditions in the statute that a reviewer should know.
    notes: str | None = None

    @model_validator(mode="after")
    def _one_period(self) -> ReleaseDeadline:
        if (self.days is None) == (self.months is None):
            raise ValueError("A deadline is a number of days or of months, not both or neither.")
        return self

    @property
    def period(self) -> str:
        if self.months:
            return f"{self.months} month{'s' if self.months > 1 else ''}"
        return f"{self.days} days"

    def due_on(self, starts_on: date) -> date:
        """The last day for the release, counting from the day the clock starts."""
        if self.days:
            return starts_on + timedelta(days=self.days)
        month = starts_on.month - 1 + (self.months or 0)
        year, month = starts_on.year + month // 12, month % 12 + 1
        return date(year, month, min(starts_on.day, calendar.monthrange(year, month)[1]))


class ReleaseTrackingStatus(StrEnum):
    #: A full release is of record, recorded by the deadline.
    RELEASED = "released"
    #: A full release is of record, recorded after the deadline.
    RELEASED_LATE = "released_late"
    #: No release is of record, and the deadline hasn't passed.
    AWAITING_RELEASE = "awaiting_release"
    #: No release is of record, the deadline has passed, and the statute's duty
    #: is to record it.
    OVERDUE = "overdue"
    #: No release is of record, and the index can't show whether the lender is
    #: late: no deadline is on file, the clock waits on a request not yet given,
    #: or the lender may deliver the release to the borrower instead of recording it.
    NOT_RELEASED = "not_released"
    #: The index answer needs a person: only candidates, only a partial release,
    #: or the mortgage wasn't found.
    NEEDS_REVIEW = "needs_review"
    #: No recorder connector covers the county, so only the deadline is known.
    NOT_CHECKED = "not_checked"


class ReleaseTrackingRecord(BaseModel):
    """Where one paid-off mortgage's release stands against the state's deadline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.release_tracking_status"
    schema_version: str = "1.0"
    record_type: Literal["release_tracking_status"] = "release_tracking_status"
    #: The county index read, when a connector could read it.
    source: RecorderSource | None = None
    jurisdiction: Jurisdiction
    query: MortgageReleaseQuery
    paid_off_on: date
    #: When the owner's written request for the release was made, if given.
    requested_on: date | None = None
    as_of: date
    status: ReleaseTrackingStatus
    deadline: ReleaseDeadline | None = None
    release_due_on: date | None = None
    #: Days since the deadline passed, once it has and no release is of record.
    days_overdue: int | None = None
    released_on: date | None = None
    #: When to look at the county's index again; None once nothing is left to wait for.
    recheck_on: date | None = None
    next_action: str
    #: The county index's answer this is judged from, when a connector could ask it.
    release_search: MortgageReleaseRecord | None = None
    notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


def track_release(
    *,
    jurisdiction: Jurisdiction,
    query: MortgageReleaseQuery,
    paid_off_on: date,
    as_of: date,
    deadline: ReleaseDeadline | None,
    release_search: MortgageReleaseRecord | None,
    requested_on: date | None = None,
) -> ReleaseTrackingRecord:
    """Judge the county's answer, if there is one, against the state's deadline."""
    starts_on = (
        None
        if deadline is None
        else paid_off_on
        if deadline.clock_start is ClockStart.PAYOFF
        else requested_on
    )
    due = deadline.due_on(starts_on) if deadline and starts_on else None
    notes = _deadline_notes(deadline, jurisdiction, paid_off_on, requested_on)

    released_on: date | None = None
    if release_search is None:
        status = ReleaseTrackingStatus.NOT_CHECKED
    elif release_search.status is ReleaseFindingStatus.RELEASED:
        released_on = _released_on(release_search)
        late = due is not None and released_on is not None and released_on > due
        status = ReleaseTrackingStatus.RELEASED_LATE if late else ReleaseTrackingStatus.RELEASED
        if released_on is None:
            notes.append(
                "The release's recording date isn't in the index, so whether it was on time "
                "can't be told."
            )
    elif release_search.status is ReleaseFindingStatus.NOT_RELEASED:
        if due is None:
            status = ReleaseTrackingStatus.NOT_RELEASED
        elif as_of <= due:
            status = ReleaseTrackingStatus.AWAITING_RELEASE
        elif deadline and deadline.lender_records:
            status = ReleaseTrackingStatus.OVERDUE
        else:
            status = ReleaseTrackingStatus.NOT_RELEASED
    else:
        status = ReleaseTrackingStatus.NEEDS_REVIEW

    overdue = status is ReleaseTrackingStatus.OVERDUE
    return ReleaseTrackingRecord(
        source=release_search.source if release_search else None,
        jurisdiction=jurisdiction,
        query=query,
        paid_off_on=paid_off_on,
        requested_on=requested_on,
        as_of=as_of,
        status=status,
        deadline=deadline,
        release_due_on=due,
        days_overdue=(as_of - due).days if overdue and due else None,
        released_on=released_on,
        recheck_on=_recheck_on(status, as_of, due),
        next_action=_next_action(status, as_of, due, deadline, released_on, jurisdiction),
        release_search=release_search,
        notes=notes,
    )


def _deadline_notes(
    deadline: ReleaseDeadline | None,
    jurisdiction: Jurisdiction,
    paid_off_on: date,
    requested_on: date | None,
) -> list[str]:
    if deadline is None:
        return [
            f"No statutory release deadline for {jurisdiction.state} is on file, so whether "
            "the lender is late can't be told."
        ]
    if deadline.clock_start is ClockStart.PAYOFF:
        start = f"the payoff, taken as {paid_off_on.isoformat()}"
    elif requested_on:
        start = f"the owner's written request, given as {requested_on.isoformat()}"
    else:
        start = "the owner's written request, and none was given"
    notes = [
        f"{deadline.citation}: {deadline.period} from {start}. What starts it: "
        f"{deadline.trigger}. What's due: {deadline.duty}."
    ]
    if not deadline.lender_records:
        notes.append(
            "The lender may deliver the release to the borrower instead of recording it, so an "
            "empty index doesn't show it was late."
        )
    if deadline.notes:
        notes.append(deadline.notes)
    if deadline.alternative_release:
        citation = f" ({deadline.alternative_citation})" if deadline.alternative_citation else ""
        notes.append(f"Without the lender: {deadline.alternative_release}{citation}")
    return notes


def _released_on(record: MortgageReleaseRecord) -> date | None:
    """When the full release was recorded: the earliest, if the index shows more than one."""
    dates = [
        match.release.recorded_on
        for match in record.releases
        if match.release.kind is InstrumentKind.RELEASE and match.release.recorded_on
    ]
    return min(dates) if dates else None


def _recheck_on(status: ReleaseTrackingStatus, as_of: date, due: date | None) -> date | None:
    week = as_of + timedelta(days=RECHECK_EVERY_DAYS)
    if status is ReleaseTrackingStatus.AWAITING_RELEASE and due is not None:
        # Look again within a week, and once more the day after the deadline.
        return min(week, due + timedelta(days=1))
    if status in (ReleaseTrackingStatus.OVERDUE, ReleaseTrackingStatus.NOT_RELEASED):
        return week
    if status is ReleaseTrackingStatus.NOT_CHECKED and due is not None:
        return max(due + timedelta(days=1), as_of)
    return None


def _next_action(
    status: ReleaseTrackingStatus,
    as_of: date,
    due: date | None,
    deadline: ReleaseDeadline | None,
    released_on: date | None,
    jurisdiction: Jurisdiction,
) -> str:
    county = jurisdiction.county or "the county"
    if status is ReleaseTrackingStatus.RELEASED_LATE and due and released_on:
        return (
            f"The release was recorded {(released_on - due).days} days after the deadline. "
            "Confirm it against the paid-off mortgage and close the tracking."
        )
    if status in (ReleaseTrackingStatus.RELEASED, ReleaseTrackingStatus.RELEASED_LATE):
        return "Confirm the release against the paid-off mortgage and close the tracking."
    if status is ReleaseTrackingStatus.AWAITING_RELEASE and due:
        return f"Wait for the lender; the deadline is {due.isoformat()}."
    if status is ReleaseTrackingStatus.OVERDUE and due and deadline:
        action = (
            f"The deadline passed on {due.isoformat()} with no release of record. Confirm the "
            "payoff date, then contact the lender for the release."
        )
        if deadline.remedy:
            action += f" The statute's remedy: {deadline.remedy}"
        return action
    if status is ReleaseTrackingStatus.NOT_RELEASED and deadline and due is None:
        return (
            f"The deadline in {deadline.citation} runs from the owner's written request. Send "
            "one to start the clock, then track it with the request's date."
        )
    if status is ReleaseTrackingStatus.NOT_RELEASED and deadline and due:
        return (
            f"The deadline passed on {due.isoformat()}. Ask whether the lender delivered the "
            "release to the borrower, and have it recorded; if not, contact the lender."
        )
    if status is ReleaseTrackingStatus.NOT_RELEASED:
        return "Contact the lender for the release, and check the index again."
    if status is ReleaseTrackingStatus.NEEDS_REVIEW:
        return (
            "A reviewer decides from the county's answer which release, if any, is this "
            "mortgage's, or confirms the mortgage's recording reference."
        )
    if due:
        return (
            f"No connector reads {county}'s index. Check its records by hand after "
            f"{due.isoformat()}, the deadline."
        )
    return f"Check {county}'s records for the release by hand."

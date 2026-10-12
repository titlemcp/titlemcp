from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import patch

from pydantic import ValidationError

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import (
    InstrumentKind,
    MortgageReleaseQuery,
    MortgageReleaseRecord,
    RecordedInstrument,
    RecorderSource,
    ReleaseFindingStatus,
    ReleaseMatch,
    ReleaseMatchBasis,
)
from title_mcp.domain.release_deadlines import RELEASE_DEADLINES, deadline_for
from title_mcp.domain.release_tracking import (
    ClockStart,
    ReleaseDeadline,
    ReleaseTrackingRecord,
    ReleaseTrackingStatus,
    track_release,
)
from title_mcp.mcp.server import create_mcp_server
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import (
    SourceCitation,
    SourceDescriptor,
    SourceKind,
    SourceResult,
    SourceResultStatus,
)
from title_mcp.state.memory import InMemoryWorkflowRepository

SAMPLE = Jurisdiction(state="XX", county="Sample County")
QUERY = MortgageReleaseQuery(mortgage_instrument_number="202001150101", paid_off_on="2026-05-01")
PAID_OFF = date(2026, 5, 1)
#: An invented statute: 60 days from payoff to record a satisfaction.
DEADLINE = ReleaseDeadline(
    state="XX",
    days=60,
    trigger="receiving payment in full",
    duty="the mortgagee must record a satisfaction",
    citation="Sample Code § 1-101",
    url="https://example.test/code/1-101",
    remedy="$500 and attorney fees, after a written demand",
    demand_required=True,
    demand_wait_days=30,
    alternative_release="A title agent may record an affidavit of payoff.",
    alternative_citation="Sample Code § 1-102",
)


def _search(
    status: ReleaseFindingStatus, *released_on: date, kind: InstrumentKind = InstrumentKind.RELEASE
) -> MortgageReleaseRecord:
    return MortgageReleaseRecord(
        source=RecorderSource(source_id="fake-sample-recorder", source_name="Sample Recorder"),
        jurisdiction=SAMPLE,
        query=QUERY,
        status=status,
        releases=[
            ReleaseMatch(
                release=RecordedInstrument(
                    instrument_number=f"20260{n}", recorded_on=day, kind=kind
                ),
                basis=ReleaseMatchBasis.INDEX_REFERENCE,
            )
            for n, day in enumerate(released_on)
        ],
    )


#: The same statute, with the clock starting only at the owner's written request.
ON_REQUEST = DEADLINE.model_copy(update={"clock_start": ClockStart.REQUEST, "days": 30})
#: The same statute, letting the lender deliver the release instead of recording it.
DELIVERS = DEADLINE.model_copy(update={"lender_records": False})


def _track(
    search: MortgageReleaseRecord | None,
    *,
    as_of: date,
    deadline=DEADLINE,
    requested_on: date | None = None,
):
    return track_release(
        jurisdiction=SAMPLE,
        query=QUERY,
        paid_off_on=PAID_OFF,
        as_of=as_of,
        deadline=deadline,
        release_search=search,
        requested_on=requested_on,
    )


class DeadlineTests(unittest.TestCase):
    def test_calendar_days_count_every_day(self) -> None:
        self.assertEqual(DEADLINE.due_on(PAID_OFF), date(2026, 6, 30))

    def test_months_end_on_the_same_day_or_the_last_of_a_short_month(self) -> None:
        deadline = DEADLINE.model_copy(update={"days": None, "months": 3})

        self.assertEqual(deadline.due_on(date(2026, 5, 1)), date(2026, 8, 1))
        self.assertEqual(deadline.due_on(date(2026, 11, 30)), date(2027, 2, 28))
        self.assertEqual(deadline.period, "3 months")

    def test_a_deadline_is_days_or_months(self) -> None:
        fields = DEADLINE.model_dump()
        for days, months in ((None, None), (30, 1)):
            with self.subTest(days=days, months=months):
                with self.assertRaises(ValidationError):
                    ReleaseDeadline.model_validate({**fields, "days": days, "months": months})

    def test_every_deadline_on_file_cites_its_statute(self) -> None:
        for state, deadline in RELEASE_DEADLINES.items():
            with self.subTest(state=state):
                self.assertEqual(state, deadline.state)
                self.assertTrue(deadline.citation)
                self.assertTrue(deadline.url.startswith("https://"))
                if deadline.demand_wait_days is not None:
                    self.assertTrue(deadline.demand_required)

    def test_a_state_without_a_deadline_on_file_has_none(self) -> None:
        for state in ("XX", "CA", "NM", None):
            with self.subTest(state=state):
                self.assertIsNone(deadline_for(state))

    def test_the_table_reads_each_statutes_clock_and_duty(self) -> None:
        ohio, texas, pennsylvania, south_carolina = (
            deadline_for(state) for state in ("OH", "tx", "PA", "SC")
        )

        self.assertEqual((ohio.days, ohio.clock_start, ohio.lender_records), (90, "payoff", True))
        # Texas lets the servicer deliver the release to the borrower instead of filing it.
        self.assertFalse(texas.lender_records)
        self.assertIs(pennsylvania.clock_start, ClockStart.REQUEST)
        self.assertEqual(south_carolina.period, "3 months")


class TrackingTests(unittest.TestCase):
    def test_a_release_recorded_by_the_deadline_is_released(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.RELEASED, date(2026, 6, 2)), as_of=date(2026, 6, 5)
        )

        self.assertIs(record.status, ReleaseTrackingStatus.RELEASED)
        self.assertEqual(record.released_on, date(2026, 6, 2))
        self.assertEqual(record.release_due_on, date(2026, 6, 30))
        self.assertIsNone(record.recheck_on)
        self.assertEqual(record.source.source_id, "fake-sample-recorder")

    def test_a_release_recorded_after_it_is_released_late(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.RELEASED, date(2026, 7, 10)), as_of=date(2026, 7, 12)
        )

        self.assertIs(record.status, ReleaseTrackingStatus.RELEASED_LATE)
        self.assertIn("10 days after the deadline", record.next_action)

    def test_the_earliest_full_release_is_the_recording_date(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.RELEASED, date(2026, 7, 10), date(2026, 6, 20)),
            as_of=date(2026, 7, 12),
        )

        self.assertEqual(record.released_on, date(2026, 6, 20))
        self.assertIs(record.status, ReleaseTrackingStatus.RELEASED)

    def test_nothing_of_record_before_the_deadline_is_awaited(self) -> None:
        record = _track(_search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2026, 5, 20))

        self.assertIs(record.status, ReleaseTrackingStatus.AWAITING_RELEASE)
        self.assertEqual(record.recheck_on, date(2026, 5, 27))
        self.assertIsNone(record.days_overdue)

    def test_the_last_recheck_before_the_deadline_is_the_day_after_it(self) -> None:
        record = _track(_search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2026, 6, 28))

        self.assertEqual(record.recheck_on, date(2026, 7, 1))

    def test_nothing_of_record_after_the_deadline_is_overdue_with_the_statutes_steps(self) -> None:
        record = _track(_search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2026, 7, 15))

        self.assertIs(record.status, ReleaseTrackingStatus.OVERDUE)
        self.assertEqual(record.days_overdue, 15)
        self.assertEqual(record.recheck_on, date(2026, 7, 22))
        self.assertIn("remedy: $500 and attorney fees, after a written demand", record.next_action)
        self.assertIn(
            "Without the lender: A title agent may record an affidavit of payoff. "
            "(Sample Code § 1-102)",
            record.notes,
        )
        self.assertTrue(record.requires_human_review)

    def test_where_the_lender_may_deliver_instead_an_empty_index_is_not_overdue(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2026, 7, 15), deadline=DELIVERS
        )

        self.assertIs(record.status, ReleaseTrackingStatus.NOT_RELEASED)
        self.assertIsNone(record.days_overdue)
        self.assertIn("delivered the release to the borrower", record.next_action)

    def test_a_clock_that_waits_on_a_request_has_no_deadline_without_one(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.NOT_RELEASED),
            as_of=date(2026, 7, 15),
            deadline=ON_REQUEST,
        )

        self.assertIs(record.status, ReleaseTrackingStatus.NOT_RELEASED)
        self.assertIsNone(record.release_due_on)
        self.assertIn("runs from the owner's written request", record.next_action)
        self.assertIn("none was given", record.notes[0])

    def test_a_clock_that_waits_on_a_request_runs_from_it(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.NOT_RELEASED),
            as_of=date(2026, 7, 15),
            deadline=ON_REQUEST,
            requested_on=date(2026, 7, 1),
        )

        self.assertIs(record.status, ReleaseTrackingStatus.AWAITING_RELEASE)
        self.assertEqual(record.release_due_on, date(2026, 7, 31))
        self.assertEqual(record.requested_on, date(2026, 7, 1))

    def test_without_a_deadline_on_file_overdue_is_not_claimed(self) -> None:
        record = _track(
            _search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2027, 1, 1), deadline=None
        )

        self.assertIs(record.status, ReleaseTrackingStatus.NOT_RELEASED)
        self.assertIsNone(record.release_due_on)
        self.assertIn("No statutory release deadline", record.notes[0])

    def test_answers_a_person_must_judge_need_review(self) -> None:
        for finding in (
            ReleaseFindingStatus.CANDIDATES_ONLY,
            ReleaseFindingStatus.PARTIALLY_RELEASED,
            ReleaseFindingStatus.MORTGAGE_NOT_FOUND,
        ):
            with self.subTest(finding=finding):
                record = _track(_search(finding), as_of=date(2026, 7, 15))
                self.assertIs(record.status, ReleaseTrackingStatus.NEEDS_REVIEW)
                self.assertIsNone(record.recheck_on)

    def test_without_a_connector_the_deadline_says_when_to_check_by_hand(self) -> None:
        record = _track(None, as_of=date(2026, 5, 20))

        self.assertIs(record.status, ReleaseTrackingStatus.NOT_CHECKED)
        self.assertEqual(record.recheck_on, date(2026, 7, 1))
        self.assertIn("by hand after 2026-06-30", record.next_action)

    def test_the_record_is_canonical(self) -> None:
        record = _track(_search(ReleaseFindingStatus.NOT_RELEASED), as_of=date(2026, 5, 20))
        dumped = record.model_dump(mode="json")

        self.assertEqual(dumped["schema_name"], "title_mcp.release_tracking_status")
        self.assertEqual(dumped["record_type"], "release_tracking_status")
        self.assertEqual(ReleaseTrackingRecord.model_validate(dumped), record)


class _FakeReleaseSource:
    source_id = "fake-sample-recorder"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Sample County Recorder",
        kind=SourceKind.COUNTY_RECORDER,
        jurisdiction_scope=JurisdictionScope(country="US", state="XX", county="Sample County"),
    )

    def __init__(self, record: MortgageReleaseRecord | None = None) -> None:
        self.record = record
        self.queries: list[MortgageReleaseQuery] = []

    def supports(self, jurisdiction, kind=None) -> bool:
        return (kind is None or kind == SourceKind.COUNTY_RECORDER) and (
            self.descriptor.jurisdiction_scope.matches(jurisdiction)
        )

    async def query(self, query):  # pragma: no cover - not used by the tracking tool
        raise NotImplementedError

    async def find_release(self, jurisdiction, query) -> SourceResult:
        self.queries.append(query)
        if self.record is None:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=["The recorder's site didn't answer."],
            )
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=[self.record.model_dump(mode="json")],
            citations=[SourceCitation(label="Sample Recorder document 202001150101")],
        )


class ReleaseTrackingToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.dict(RELEASE_DEADLINES, {"XX": DEADLINE})
        patcher.start()
        self.addCleanup(patcher.stop)

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
        result = await server.call_tool("release_tracking_status", arguments)
        return json.loads(result.content[0].text)

    async def test_the_countys_answer_is_judged_against_the_deadline(self) -> None:
        source = _FakeReleaseSource(_search(ReleaseFindingStatus.NOT_RELEASED))

        result = await self._call(
            self._server(source),
            state="XX",
            county="Sample",
            mortgage_instrument_number="202001150101",
            paid_off_on="2026-05-01",
            as_of="2026-07-15",
        )

        self.assertEqual(result["status"], "succeeded")
        [record] = result["records"]
        self.assertEqual(record["status"], "overdue")
        self.assertEqual(record["release_due_on"], "2026-06-30")
        self.assertEqual(record["deadline"]["citation"], "Sample Code § 1-101")
        self.assertEqual(source.queries[0].paid_off_on, PAID_OFF)
        labels = [citation["label"] for citation in result["citations"]]
        self.assertEqual(labels, ["Sample Recorder document 202001150101", "Sample Code § 1-101"])

    async def test_a_request_date_starts_a_clock_that_waits_on_one(self) -> None:
        with patch.dict(RELEASE_DEADLINES, {"XX": ON_REQUEST}):
            result = await self._call(
                self._server(_FakeReleaseSource(_search(ReleaseFindingStatus.NOT_RELEASED))),
                state="XX",
                county="Sample",
                mortgage_instrument_number="202001150101",
                paid_off_on="2026-05-01",
                release_requested_on="2026-07-01",
                as_of="2026-08-05",
            )

        record = result["records"][0]
        self.assertEqual(record["status"], "overdue")
        self.assertEqual(record["release_due_on"], "2026-07-31")

    async def test_without_a_connector_the_deadline_alone_is_partial(self) -> None:
        result = await self._call(
            self._server(),
            state="XX",
            county="Sample County",
            borrower_names=["Sample Borrower"],
            paid_off_on="2026-05-01",
            as_of="2026-05-20",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"][0]["status"], "not_checked")
        self.assertIn("No installed recorder connector", result["warnings"][0])

    async def test_an_index_that_cannot_be_read_falls_back_to_the_deadline(self) -> None:
        result = await self._call(
            self._server(_FakeReleaseSource()),
            state="XX",
            county="Sample",
            mortgage_instrument_number="202001150101",
            paid_off_on="2026-05-01",
            as_of="2026-05-20",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"][0]["status"], "not_checked")
        self.assertIn("didn't answer", result["warnings"][0])

    async def test_a_payoff_date_and_something_to_search_for_are_required(self) -> None:
        server = self._server(_FakeReleaseSource())

        bad_date = await self._call(
            server, state="XX", county="Sample", mortgage_instrument_number="1", paid_off_on="May"
        )
        nothing = await self._call(server, state="XX", county="Sample", paid_off_on="2026-05-01")
        bad_as_of = await self._call(
            server,
            state="XX",
            county="Sample",
            mortgage_instrument_number="1",
            paid_off_on="2026-05-01",
            as_of="soon",
        )
        bad_request = await self._call(
            server,
            state="XX",
            county="Sample",
            mortgage_instrument_number="1",
            paid_off_on="2026-05-01",
            release_requested_on="last week",
        )

        for result in (bad_date, nothing, bad_as_of, bad_request):
            self.assertEqual(result["status"], "requires_configuration")
        self.assertIn("instrument number", nothing["warnings"][0])

    async def test_a_state_that_is_not_one_asks_for_its_code(self) -> None:
        result = await self._call(
            self._server(), state="Columbia", county="X", paid_off_on="2026-05-01"
        )

        self.assertEqual(result["status"], "requires_configuration")


if __name__ == "__main__":
    unittest.main()

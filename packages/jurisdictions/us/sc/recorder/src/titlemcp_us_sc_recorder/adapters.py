from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class SouthCarolinaReleaseTrackingAdapter:
    """Plans following a paid-off mortgage until its release is of record.

    South Carolina gives the holder three months from a request sent by certified
    mail, or delivered with proof, to enter satisfaction (S.C. Code § 29-3-310).
    The three months start only with that request, so the plan asks the lender
    first.
    """

    adapter_id = "us-sc-recorder-release-tracking"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.RELEASE_TRACKING})
    scope = JurisdictionScope(country="US", state="SC")

    def supports(self, jurisdiction) -> bool:
        return self.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=request.jurisdiction,
            kind=request.kind,
            required_review=True,
            risk_level=RiskLevel.MEDIUM,
            steps=[
                WorkflowAction(
                    label="Check the county records for the release",
                    description=(
                        "Run mortgage_release_search with the mortgage's instrument number "
                        "from the commitment, or the borrower and the payoff date."
                    ),
                    metadata={"tool": "mortgage_release_search", "source_kind": "county_recorder"},
                ),
                WorkflowAction(
                    label="Ask the lender in writing if none is recorded",
                    description=(
                        "South Carolina gives the holder three months from a request sent by "
                        "certified mail, or delivered with proof, to enter satisfaction (S.C. Code "
                        "§ 29-3-310)."
                    ),
                    metadata={"deadline_months_after_request": "3"},
                ),
                WorkflowAction(
                    label="Review the release against the mortgage",
                    description=(
                        "A reviewer confirms the release discharges this mortgage, especially "
                        "when it was identified from the parties rather than the number."
                    ),
                ),
            ],
            routing_hints={"country": "US", "state": "SC", "source": "recorder"},
        )

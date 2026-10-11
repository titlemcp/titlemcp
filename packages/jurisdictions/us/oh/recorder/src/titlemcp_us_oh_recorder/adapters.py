from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class OhioReleaseTrackingAdapter:
    """Plans following a paid-off mortgage until its release is of record.

    Ohio gives the lender 90 days from payoff to record the release (R.C.
    5301.36(B)), so the plan checks the county's index, and only a release
    still missing near that deadline goes to the lender.
    """

    adapter_id = "us-oh-recorder-release-tracking"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.RELEASE_TRACKING})
    scope = JurisdictionScope(country="US", state="OH")

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
                    label="Check the county recorder for the release",
                    description=(
                        "Run mortgage_release_search with the mortgage's instrument number "
                        "from the commitment, or the borrower and the payoff date."
                    ),
                    metadata={"tool": "mortgage_release_search", "source_kind": "county_recorder"},
                ),
                WorkflowAction(
                    label="Follow up with the lender if none is recorded",
                    description=(
                        "Ohio gives the lender 90 days from payoff to record the release "
                        "(R.C. 5301.36(B)). Check again before then, and ask the lender if it "
                        "is still missing."
                    ),
                    metadata={"deadline_days_after_payoff": "90"},
                ),
                WorkflowAction(
                    label="Review the release against the mortgage",
                    description=(
                        "A reviewer confirms the release discharges this mortgage, especially "
                        "when it was identified from the parties rather than the number."
                    ),
                ),
            ],
            routing_hints={"country": "US", "state": "OH", "source": "recorder"},
        )

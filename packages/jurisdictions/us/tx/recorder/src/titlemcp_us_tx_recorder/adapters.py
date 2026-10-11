from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class TexasReleaseTrackingAdapter:
    """Plans following a paid-off mortgage until its release is of record.

    Texas gives the lender or servicer of a home loan 60 days from receiving the
    payoff to deliver the release of lien to the borrower or file it with the
    county clerk (Tex. Fin. Code § 343.108). The release may go to the borrower
    instead of the record, so the plan asks the lender where it went before
    treating it as missing.
    """

    adapter_id = "us-tx-recorder-release-tracking"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.RELEASE_TRACKING})
    scope = JurisdictionScope(country="US", state="TX")

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
                    label="Ask the lender where the release went if none is recorded",
                    description=(
                        "Texas gives the lender 60 days from receiving the payoff to deliver the "
                        "release of lien to the borrower or file it for recording (Tex. Fin. Code "
                        "§ 343.108); 30 days after a written request made within 20 days of payoff."
                        " If none is recorded, ask whether it was delivered to the borrower "
                        "instead."
                    ),
                    metadata={"deadline_days_after_payoff": "60"},
                ),
                WorkflowAction(
                    label="Review the release against the mortgage",
                    description=(
                        "A reviewer confirms the release discharges this mortgage, especially "
                        "when it was identified from the parties rather than the number."
                    ),
                ),
            ],
            routing_hints={"country": "US", "state": "TX", "source": "recorder"},
        )

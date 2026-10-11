from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class ColoradoReleaseTrackingAdapter:
    """Plans following a paid-off mortgage until its release is of record.

    Colorado gives the holder 90 days after the debt is paid to file the release
    documents with the county's public trustee (C.R.S. 38-35-124), who then
    records the release of the deed of trust.
    """

    adapter_id = "us-co-recorder-release-tracking"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.RELEASE_TRACKING})
    scope = JurisdictionScope(country="US", state="CO")

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
                    label="Ask the holder if none is recorded",
                    description=(
                        "Colorado gives the holder 90 days after the debt is paid to file the "
                        "release documents with the county's public trustee (C.R.S. 38-35-124). If "
                        "none is recorded by then, ask the holder whether it filed them."
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
            routing_hints={"country": "US", "state": "CO", "source": "recorder"},
        )

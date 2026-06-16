from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class OhioCountyAuditorAdapter:
    """Plans a county-auditor property/assessment lookup for Ohio counties.

    State-scoped: any Ohio county auditor running iasWorld (see
    ``titlemcp_us_oh_auditor.sites``) can use this plan. A county-specific
    adapter, if added later, outranks it by specificity.
    """

    adapter_id = "us-oh-auditor-property-assessment"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
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
                    label="Query county auditor property search",
                    description=(
                        "Use the county auditor (iasWorld) source connector to retrieve "
                        "parcel, ownership, valuation, and tax-status records."
                    ),
                    metadata={"source_kind": "tax_authority", "platform": "tyler-iasworld"},
                ),
                WorkflowAction(
                    label="Normalize property assessment record",
                    description="Map auditor results to title_mcp.property_assessment_record.",
                ),
                WorkflowAction(
                    label="Review assessment facts",
                    description="Human reviewer confirms parcel, ownership, and tax figures.",
                ),
            ],
            routing_hints={
                "country": "US",
                "state": "OH",
                "source": "auditor",
                "platform": "tyler-iasworld",
            },
        )

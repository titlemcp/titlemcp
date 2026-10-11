from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class ShelbyCountyTaxCertificateAdapter:
    """Plans confirming a Shelby County parcel's property tax before closing.

    The Trustee collects county tax. City tax, such as the City of Memphis's,
    is confirmed separately.
    """

    adapter_id = "us-tn-shelby-tax-certificate"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
    scope = JurisdictionScope(country="US", state="TN", county="Shelby County")

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
                    label="Read the parcel's county tax status",
                    description=(
                        "Run property_tax_status_search with the parcel number. It returns "
                        "each year's county bill: billed, paid and owed, interest and fees, "
                        "and any tax sale flag."
                    ),
                    metadata={"tool": "property_tax_status_search", "source_kind": "tax_authority"},
                ),
                WorkflowAction(
                    label="Confirm city tax with the city",
                    description=(
                        "City property tax, such as the City of Memphis's, isn't in the "
                        "Trustee's county bills. Confirm it with the city that bills it."
                    ),
                ),
                WorkflowAction(
                    label="Confirm the payoff with the Trustee",
                    description=(
                        "For a balance owed, confirm the amount with interest to the closing "
                        "date with the Shelby County Trustee. A reviewer confirms taxes and "
                        "any tax sale against the commitment."
                    ),
                ),
            ],
            routing_hints={
                "country": "US",
                "state": "TN",
                "county": "Shelby County",
                "source": "tax_authority",
            },
        )

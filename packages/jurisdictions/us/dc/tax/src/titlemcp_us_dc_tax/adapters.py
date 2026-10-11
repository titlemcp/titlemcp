from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class DistrictOfColumbiaTaxCertificateAdapter:
    """Plans confirming a District parcel's real property tax before closing.

    The open data extract is refreshed every weekday, so it shows the account as
    of the last refresh; a payment made since then isn't in it.
    """

    adapter_id = "us-dc-tax-certificate"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
    scope = JurisdictionScope(country="US", state="DC")

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
                    label="Read the parcel's tax status",
                    description=(
                        "Run property_tax_status_search with the parcel's square, suffix and "
                        "lot. It returns each half's tax, payments and balance, prior years, "
                        "tax sale flags and special assessments."
                    ),
                    metadata={"tool": "property_tax_status_search", "source_kind": "tax_authority"},
                ),
                WorkflowAction(
                    label="Confirm the payoff with the Office of Tax and Revenue",
                    description=(
                        "The extract is refreshed every weekday. For a balance owed, or a "
                        "payment made since the extract's date, confirm the amount to the "
                        "closing date on MyTax.DC.gov or with the Office of Tax and Revenue."
                    ),
                ),
                WorkflowAction(
                    label="Review taxes, assessments and tax sale flags",
                    description=(
                        "A reviewer confirms the taxes, special assessments and any tax sale "
                        "against the commitment."
                    ),
                ),
            ],
            routing_hints={"country": "US", "state": "DC", "source": "tax_authority"},
        )

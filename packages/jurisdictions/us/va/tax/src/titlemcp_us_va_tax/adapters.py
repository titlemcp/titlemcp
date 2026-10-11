from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest
from titlemcp_us_va_tax.sites import VA_TAX_SITES


class VirginiaTaxCertificateAdapter:
    """Plans confirming a parcel's real estate tax before closing.

    Covers the counties in ``sites.py``, whose sites are read live, so a payment
    posted there today is in the answer.
    """

    adapter_id = "us-va-tax-certificate"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
    scopes = tuple(site.jurisdiction_scope for site in VA_TAX_SITES)

    def supports(self, jurisdiction) -> bool:
        return any(scope.matches(jurisdiction) for scope in self.scopes)

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
                        "Run property_tax_status_search with the parcel's number. It reads "
                        "the county's site and returns each year's tax, payments and balance, "
                        "with installments and due dates."
                    ),
                    metadata={"tool": "property_tax_status_search", "source_kind": "tax_authority"},
                ),
                WorkflowAction(
                    label="Confirm the payoff with the collector",
                    description=(
                        "Penalty and interest accrue after each half's due date. Confirm the "
                        "amount due through the closing date with the Department of Tax "
                        "Administration, and any town tax with the town."
                    ),
                ),
                WorkflowAction(
                    label="Review taxes against the commitment",
                    description=(
                        "A reviewer confirms the taxes, any delinquency and the payoff "
                        "against the commitment."
                    ),
                ),
            ],
            routing_hints={"country": "US", "state": "VA", "source": "tax_authority"},
        )

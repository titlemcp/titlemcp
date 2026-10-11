from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest
from titlemcp_us_nm_tax.sites import NM_TAX_SITES


class NewMexicoTaxCertificateAdapter:
    """Plans confirming a parcel's property tax before closing.

    Covers the counties in ``sites.py``, whose sites are read live, so a payment
    posted there today is in the answer.
    """

    adapter_id = "us-nm-tax-certificate"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
    scopes = tuple(site.jurisdiction_scope for site in NM_TAX_SITES)

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
                        "Interest and penalty accrue once a half is delinquent. Confirm the "
                        "amount due through the closing date with the County Treasurer."
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
            routing_hints={"country": "US", "state": "NM", "source": "tax_authority"},
        )

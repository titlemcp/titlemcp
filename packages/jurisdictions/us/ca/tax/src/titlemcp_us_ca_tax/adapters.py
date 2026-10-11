from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class ContraCostaTaxCertificateAdapter:
    """Plans confirming a Contra Costa parcel's secured property tax before closing.

    The county's lookup shows each installment as of the day it is read. A
    payment still pending, a correction, or a supplemental or redemption bill it
    doesn't read are reasons to confirm with the Treasurer-Tax Collector.
    """

    adapter_id = "us-ca-contra-costa-tax-certificate"
    priority = 210
    workflow_kinds = frozenset({WorkflowKind.TAX_CERTIFICATE})
    scope = JurisdictionScope(country="US", state="CA", county="Contra Costa County")

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
                        "Run property_tax_status_search with the parcel's APN. It returns each "
                        "installment of the current and prior years: amount, the last day to "
                        "pay before it is delinquent, and whether it is paid."
                    ),
                    metadata={"tool": "property_tax_status_search", "source_kind": "tax_authority"},
                ),
                WorkflowAction(
                    label="Confirm the payoff with the Treasurer-Tax Collector",
                    description=(
                        "For an installment owed, a pending payment, or a supplemental or "
                        "redemption bill, confirm the amount to the closing date with the "
                        "Contra Costa County Treasurer-Tax Collector."
                    ),
                ),
                WorkflowAction(
                    label="Review taxes and supplemental bills",
                    description=(
                        "A reviewer confirms the installments, any supplemental bills and any "
                        "defaulted taxes against the commitment."
                    ),
                ),
            ],
            routing_hints={
                "country": "US",
                "state": "CA",
                "county": "Contra Costa County",
                "source": "tax_authority",
            },
        )

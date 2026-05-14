from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import RiskLevel, WorkflowAction, WorkflowKind, WorkflowRequest


class FranklinCountyOhioRecorderAdapter:
    adapter_id = "us-oh-franklin-recorder-public-records"
    priority = 220
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})
    scope = JurisdictionScope(country="US", state="OH", county="Franklin County")

    def supports(self, jurisdiction):
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
                    label="Query Franklin County recorder",
                    description="Use the Franklin County recorder source client.",
                    metadata={"source": "franklin_county_recorder"},
                ),
                WorkflowAction(
                    label="Normalize recorded document hits",
                    description="Normalize instrument, party, date, book/page, and document type.",
                ),
                WorkflowAction(
                    label="Review public-record matches",
                    description="Human reviewer confirms party and property matches.",
                ),
            ],
            routing_hints={
                "country": "US",
                "state": "OH",
                "county": "Franklin County",
                "source": "recorder",
            },
        )

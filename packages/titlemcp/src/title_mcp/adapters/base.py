from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from title_mcp.domain.models import (
    Jurisdiction,
    RiskLevel,
    WorkflowAction,
    WorkflowKind,
    WorkflowRequest,
)


class JurisdictionScope(BaseModel):
    country: str | None = None
    state: str | None = None
    county: str | None = None
    municipality: str | None = None

    def matches(self, jurisdiction: Jurisdiction) -> bool:
        return jurisdiction.matches(
            country=self.country,
            state=self.state,
            county=self.county,
            municipality=self.municipality,
        )

    @property
    def specificity(self) -> int:
        return sum(
            1
            for value in [self.country, self.state, self.county, self.municipality]
            if value
        )


class AdapterPlan(BaseModel):
    adapter_id: str
    jurisdiction: Jurisdiction
    kind: WorkflowKind
    required_review: bool = True
    risk_level: RiskLevel = RiskLevel.MEDIUM
    steps: list[WorkflowAction] = Field(default_factory=list)
    external_requirements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    routing_hints: dict[str, str] = Field(default_factory=dict)


class JurisdictionAdapter(Protocol):
    adapter_id: str
    priority: int
    workflow_kinds: frozenset[WorkflowKind] | None

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        """Return true when this adapter handles the jurisdiction."""

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        """Create jurisdiction-aware workflow steps for a request."""

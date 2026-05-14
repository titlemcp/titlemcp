from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import (
    Jurisdiction,
    RiskLevel,
    WorkflowAction,
    WorkflowKind,
    WorkflowRequest,
)


class ConfiguredJurisdictionAdapterSpec(BaseModel):
    adapter_id: str
    scope: JurisdictionScope
    workflow_kinds: frozenset[WorkflowKind] | None = None
    priority: int = 100
    required_review: bool = True
    risk_level: RiskLevel = RiskLevel.MEDIUM
    steps: list[WorkflowAction] = Field(default_factory=list)
    external_requirements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    routing_hints: dict[str, str] = Field(default_factory=dict)


class ConfiguredAdaptersFile(BaseModel):
    adapters: list[ConfiguredJurisdictionAdapterSpec] = Field(default_factory=list)


class ConfigurableJurisdictionAdapter:
    def __init__(self, spec: ConfiguredJurisdictionAdapterSpec) -> None:
        self._spec = spec
        self.adapter_id = spec.adapter_id
        self.priority = spec.priority
        self.workflow_kinds = spec.workflow_kinds

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return self._spec.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=request.jurisdiction,
            kind=request.kind,
            required_review=request.require_human_review and self._spec.required_review,
            risk_level=self._spec.risk_level,
            steps=[step.model_copy(deep=True) for step in self._spec.steps],
            external_requirements=list(self._spec.external_requirements),
            warnings=list(self._spec.warnings),
            routing_hints={
                "country": request.jurisdiction.country,
                **self._spec.routing_hints,
            },
        )


def load_configured_adapters(path: str | Path) -> list[ConfigurableJurisdictionAdapter]:
    with Path(path).open("r", encoding="utf-8") as config_file:
        payload = json.load(config_file)
    config = ConfiguredAdaptersFile.model_validate(payload)
    return [ConfigurableJurisdictionAdapter(spec) for spec in config.adapters]

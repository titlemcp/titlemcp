from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class CapabilityType(StrEnum):
    MCP_TOOLSET = "mcp_toolset"
    WORKFLOW_ADAPTER = "workflow_adapter"
    GOVERNMENT_SOURCE = "government_source"
    VENDOR_CONNECTOR = "vendor_connector"
    DOCUMENT_ANALYZER = "document_analyzer"
    SCHEMA_PACK = "schema_pack"
    POLICY_PACK = "policy_pack"


class CapabilityManifest(BaseModel):
    """Install-time description of a TitleMCP extension package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    capability_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    description: str | None = None
    package_name: str | None = None
    capability_types: list[CapabilityType] = Field(default_factory=list)
    jurisdiction_scopes: list[JurisdictionScope] = Field(default_factory=list)
    workflow_kinds: list[WorkflowKind] = Field(default_factory=list)
    entry_points: dict[str, str] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    review_required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def supports(
        self,
        jurisdiction: Jurisdiction,
        kind: WorkflowKind | None = None,
        capability_type: CapabilityType | None = None,
    ) -> bool:
        if capability_type and capability_type not in self.capability_types:
            return False
        if kind and self.workflow_kinds and kind not in self.workflow_kinds:
            return False
        return not self.jurisdiction_scopes or any(
            scope.matches(jurisdiction) for scope in self.jurisdiction_scopes
        )

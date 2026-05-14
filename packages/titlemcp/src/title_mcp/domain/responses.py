from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from title_mcp.domain.models import WorkflowAction, WorkflowKind, WorkflowStatus


class WorkflowSummary(BaseModel):
    workflow_id: str
    kind: WorkflowKind
    status: WorkflowStatus
    file_number: str
    jurisdiction: str
    adapter_id: str | None = None
    next_actions: list[WorkflowAction] = Field(default_factory=list)


class WorkflowToolResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    message: str
    next_actions: list[WorkflowAction] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummary]

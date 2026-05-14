from __future__ import annotations

from typing import Any

from title_mcp.domain.models import (
    Address,
    AuditActor,
    Jurisdiction,
    OrderRef,
    ReviewDecision,
    WorkflowAction,
    WorkflowKind,
    WorkflowRecord,
    WorkflowRequest,
    WorkflowStatus,
)
from title_mcp.domain.responses import WorkflowSummary, WorkflowToolResponse
from title_mcp.state.base import WorkflowRepository
from title_mcp.workflows.engine import WorkflowEngine


class WorkflowService:
    def __init__(self, *, repository: WorkflowRepository, engine: WorkflowEngine) -> None:
        self._repository = repository
        self._engine = engine

    async def create_workflow(
        self,
        *,
        kind: WorkflowKind,
        file_number: str,
        jurisdiction: Jurisdiction,
        payload: dict[str, Any],
        requested_by: str = "mcp",
        require_human_review: bool = True,
        property_address: Address | None = None,
        buyer: str | None = None,
        seller: str | None = None,
    ) -> WorkflowRecord:
        request = WorkflowRequest(
            kind=kind,
            order=OrderRef(
                file_number=file_number,
                property_address=property_address,
                buyer=buyer,
                seller=seller,
            ),
            jurisdiction=jurisdiction,
            payload=payload,
            require_human_review=require_human_review,
            requested_by=AuditActor(
                actor_id=requested_by,
                actor_type="user",
                display_name=requested_by,
            ),
        )
        return await self._engine.create(request)

    async def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        record = await self._repository.get(workflow_id)
        if record is None:
            raise LookupError(f"Workflow not found: {workflow_id}")
        return record

    async def list_workflows(
        self,
        *,
        file_number: str | None = None,
        status: WorkflowStatus | None = None,
        kind: WorkflowKind | None = None,
        limit: int = 50,
    ) -> list[WorkflowRecord]:
        return await self._repository.list(
            file_number=file_number,
            status=status,
            kind=kind,
            limit=limit,
        )

    async def submit_review(
        self,
        *,
        workflow_id: str,
        decision: ReviewDecision,
        reviewer: str,
        notes: str | None = None,
    ) -> WorkflowRecord:
        return await self._engine.submit_review(
            workflow_id,
            decision=decision,
            reviewer=reviewer,
            notes=notes,
        )

    @staticmethod
    def _planned_actions(record: WorkflowRecord) -> list[WorkflowAction]:
        next_actions = [
            WorkflowAction.model_validate(task.result["planned_action"])
            for task in record.tasks
            if task.result and "planned_action" in task.result
        ]
        return next_actions

    @staticmethod
    def summarize(record: WorkflowRecord) -> WorkflowSummary:
        return WorkflowSummary(
            workflow_id=record.id,
            kind=record.kind,
            status=record.status,
            file_number=record.order.file_number,
            jurisdiction=record.jurisdiction.key,
            adapter_id=record.adapter_id,
            next_actions=WorkflowService._planned_actions(record),
        )

    @staticmethod
    def to_tool_response(record: WorkflowRecord, message: str) -> WorkflowToolResponse:
        return WorkflowToolResponse(
            workflow_id=record.id,
            status=record.status,
            message=message,
            next_actions=WorkflowService._planned_actions(record),
            data=record.model_dump(mode="json"),
        )

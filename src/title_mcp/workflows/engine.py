from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from title_mcp.adapters.registry import AdapterRegistry
from title_mcp.domain.models import (
    AuditActor,
    HumanReviewRequest,
    ReviewDecision,
    ReviewStatus,
    TaskStatus,
    WorkflowRecord,
    WorkflowRequest,
    WorkflowStatus,
    WorkflowTask,
    utc_now,
)
from title_mcp.observability import current_trace_id, get_logger, trace_span
from title_mcp.state.base import WorkflowRepository


class BackgroundTaskManager:
    def __init__(self, concurrency: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    def enqueue(self, work: Callable[[], Awaitable[None]]) -> None:
        task = asyncio.create_task(self._run(work))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks))

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run(self, work: Callable[[], Awaitable[None]]) -> None:
        async with self._semaphore:
            await work()


class WorkflowEngine:
    """Coordinates workflow state while leaving legal and business decisions to reviewers."""

    def __init__(
        self,
        *,
        repository: WorkflowRepository,
        adapters: AdapterRegistry,
        concurrency: int = 4,
        auto_start: bool = True,
    ) -> None:
        self._repository = repository
        self._adapters = adapters
        self._background = BackgroundTaskManager(concurrency)
        self._auto_start = auto_start
        self._logger = get_logger(__name__)

    async def create(self, request: WorkflowRequest) -> WorkflowRecord:
        with trace_span(
            "workflow.create",
            kind=request.kind.value,
            file_number=request.order.file_number,
        ) as trace_id:
            adapter = self._adapters.resolve(request.jurisdiction, request.kind)
            plan = await adapter.plan(request)
            record = WorkflowRecord(
                kind=request.kind,
                order=request.order,
                jurisdiction=request.jurisdiction,
                payload=request.payload,
                adapter_id=plan.adapter_id,
                tasks=[
                    WorkflowTask(
                        name=step.label,
                        action_type=step.action_type,
                        result={"planned_action": step.model_dump(mode="json")},
                    )
                    for step in plan.steps
                ],
                result={
                    "external_requirements": plan.external_requirements,
                    "warnings": plan.warnings,
                    "routing_hints": plan.routing_hints,
                },
            )

            if plan.required_review:
                record.review = HumanReviewRequest(
                    risk_level=plan.risk_level,
                    prompt=(
                        f"Review {request.kind.value} workflow for order "
                        f"{request.order.file_number} in {request.jurisdiction.key} "
                        "before execution."
                    ),
                )
                record.status = WorkflowStatus.NEEDS_HUMAN_REVIEW

            record.add_audit(
                "workflow.created",
                actor=request.requested_by,
                payload={"adapter_id": plan.adapter_id, "steps": len(plan.steps)},
                trace_id=trace_id,
            )
            await self._repository.save(record)

            if self._auto_start and record.status != WorkflowStatus.NEEDS_HUMAN_REVIEW:
                self.enqueue(record.id)
            return record

    def enqueue(self, workflow_id: str) -> None:
        self._background.enqueue(lambda: self.run_once(workflow_id))

    async def run_once(self, workflow_id: str) -> WorkflowRecord | None:
        with trace_span("workflow.run_once", workflow_id=workflow_id) as trace_id:
            record = await self._repository.get(workflow_id)
            if record is None:
                self._logger.warning("workflow.not_found", extra={"workflow_id": workflow_id})
                return None

            if record.review and record.review.status == ReviewStatus.PENDING:
                record.status = WorkflowStatus.NEEDS_HUMAN_REVIEW
                record.add_audit(
                    "workflow.paused_for_review",
                    payload={"review_id": record.review.id},
                    trace_id=trace_id,
                )
                return await self._repository.save(record)

            if record.review and record.review.status in {
                ReviewStatus.REJECTED,
                ReviewStatus.CHANGES_REQUESTED,
            }:
                record.status = WorkflowStatus.CANCELLED
                record.add_audit(
                    "workflow.cancelled_by_review",
                    payload={"review_status": record.review.status.value},
                    trace_id=trace_id,
                )
                return await self._repository.save(record)

            record.status = WorkflowStatus.RUNNING
            record.touch()
            await self._repository.save(record)

            for task in record.tasks:
                if task.status != TaskStatus.QUEUED:
                    continue
                task.status = TaskStatus.RUNNING
                task.started_at = utc_now()
                await self._repository.save(record)

                task.status = TaskStatus.SUCCEEDED
                task.completed_at = utc_now()
                task.result = {
                    **(task.result or {}),
                    "execution_mode": "review_first_placeholder",
                    "message": (
                        "Task planned and marked complete; external integration is pluggable."
                    ),
                }
                record.add_audit(
                    "workflow.task_succeeded",
                    payload={"task_id": task.id, "task_name": task.name},
                    trace_id=trace_id,
                )

            record.status = WorkflowStatus.WAITING_ON_EXTERNAL
            record.result["next_state"] = (
                "Await external vendor, public-record, or staff response before completion."
            )
            record.add_audit("workflow.waiting_on_external", trace_id=trace_id)
            return await self._repository.save(record)

    async def submit_review(
        self,
        workflow_id: str,
        *,
        decision: ReviewDecision,
        reviewer: str,
        notes: str | None = None,
        actor: AuditActor | None = None,
    ) -> WorkflowRecord:
        with trace_span("workflow.submit_review", workflow_id=workflow_id) as trace_id:
            record = await self._repository.get(workflow_id)
            if record is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if record.review is None:
                record.review = HumanReviewRequest(
                    status=ReviewStatus.NOT_REQUIRED,
                    prompt="No review was required for this workflow.",
                )

            if decision == ReviewDecision.APPROVE:
                record.review.status = ReviewStatus.APPROVED
                record.status = WorkflowStatus.QUEUED
            elif decision == ReviewDecision.REJECT:
                record.review.status = ReviewStatus.REJECTED
                record.status = WorkflowStatus.CANCELLED
            else:
                record.review.status = ReviewStatus.CHANGES_REQUESTED
                record.status = WorkflowStatus.NEEDS_HUMAN_REVIEW

            record.review.reviewer = reviewer
            record.review.decision_notes = notes
            record.review.resolved_at = utc_now()
            record.add_audit(
                "workflow.review_submitted",
                actor=actor
                or AuditActor(actor_id=reviewer, actor_type="user", display_name=reviewer),
                payload={"decision": decision.value, "notes": notes},
                trace_id=trace_id or current_trace_id(),
            )
            saved = await self._repository.save(record)

            if decision == ReviewDecision.APPROVE and self._auto_start:
                self.enqueue(record.id)
            return saved

    async def drain(self) -> None:
        await self._background.drain()

    async def shutdown(self) -> None:
        await self._background.shutdown()

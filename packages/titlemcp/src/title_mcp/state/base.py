from __future__ import annotations

from typing import Protocol

from title_mcp.domain.models import WorkflowKind, WorkflowRecord, WorkflowStatus


class WorkflowRepository(Protocol):
    async def initialize(self) -> None:
        """Prepare the repository for use."""

    async def save(self, record: WorkflowRecord) -> WorkflowRecord:
        """Create or replace a workflow record."""

    async def get(self, workflow_id: str) -> WorkflowRecord | None:
        """Return a workflow by id."""

    async def list(
        self,
        *,
        file_number: str | None = None,
        status: WorkflowStatus | None = None,
        kind: WorkflowKind | None = None,
        limit: int = 50,
    ) -> list[WorkflowRecord]:
        """Return recent workflows matching optional filters."""

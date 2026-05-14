from __future__ import annotations

import json
from typing import Any

from title_mcp.domain.models import WorkflowKind, WorkflowRecord, WorkflowStatus
from title_mcp.state.base import WorkflowRepository


class PostgresWorkflowRepository(WorkflowRepository):
    """Postgres-backed repository that stores workflow records as auditable JSONB documents."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def initialize(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError(
                "Postgres state backend requires asyncpg. Install with `pip install .[postgres]`."
            ) from exc

        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS title_mcp_workflows (
                    id text PRIMARY KEY,
                    kind text NOT NULL,
                    status text NOT NULL,
                    file_number text NOT NULL,
                    jurisdiction jsonb NOT NULL,
                    record jsonb NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_title_mcp_workflows_file_number
                    ON title_mcp_workflows (file_number);
                CREATE INDEX IF NOT EXISTS idx_title_mcp_workflows_status
                    ON title_mcp_workflows (status);
                CREATE INDEX IF NOT EXISTS idx_title_mcp_workflows_kind
                    ON title_mcp_workflows (kind);
                """
            )

    async def save(self, record: WorkflowRecord) -> WorkflowRecord:
        await self._ensure_pool()
        payload = record.model_dump(mode="json")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO title_mcp_workflows
                    (id, kind, status, file_number, jurisdiction, record, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    status = EXCLUDED.status,
                    file_number = EXCLUDED.file_number,
                    jurisdiction = EXCLUDED.jurisdiction,
                    record = EXCLUDED.record,
                    updated_at = EXCLUDED.updated_at
                """,
                record.id,
                record.kind.value,
                record.status.value,
                record.order.file_number,
                json.dumps(record.jurisdiction.model_dump(mode="json")),
                json.dumps(payload),
                record.created_at,
                record.updated_at,
            )
        return record.model_copy(deep=True)

    async def get(self, workflow_id: str) -> WorkflowRecord | None:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT record FROM title_mcp_workflows WHERE id = $1",
                workflow_id,
            )
        return self._row_to_record(row) if row else None

    async def list(
        self,
        *,
        file_number: str | None = None,
        status: WorkflowStatus | None = None,
        kind: WorkflowKind | None = None,
        limit: int = 50,
    ) -> list[WorkflowRecord]:
        await self._ensure_pool()
        clauses: list[str] = []
        values: list[Any] = []

        if file_number:
            values.append(file_number)
            clauses.append(f"file_number = ${len(values)}")
        if status:
            values.append(status.value)
            clauses.append(f"status = ${len(values)}")
        if kind:
            values.append(kind.value)
            clauses.append(f"kind = ${len(values)}")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        query = f"""
            SELECT record
            FROM title_mcp_workflows
            {where}
            ORDER BY updated_at DESC
            LIMIT ${len(values)}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *values)
        return [self._row_to_record(row) for row in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _ensure_pool(self) -> None:
        if self._pool is None:
            await self.initialize()

    @staticmethod
    def _row_to_record(row: Any) -> WorkflowRecord:
        payload = row["record"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return WorkflowRecord.model_validate(payload)

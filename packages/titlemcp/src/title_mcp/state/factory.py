from __future__ import annotations

from title_mcp.settings import TitleMCPSettings
from title_mcp.state.base import WorkflowRepository
from title_mcp.state.memory import InMemoryWorkflowRepository
from title_mcp.state.postgres import PostgresWorkflowRepository


def create_repository(settings: TitleMCPSettings) -> WorkflowRepository:
    if settings.state_backend == "memory":
        return InMemoryWorkflowRepository()
    if settings.state_backend == "postgres":
        if not settings.postgres_dsn:
            raise ValueError("TITLE_MCP_POSTGRES_DSN is required when state_backend=postgres")
        return PostgresWorkflowRepository(settings.postgres_dsn)
    raise ValueError(f"Unsupported state backend: {settings.state_backend}")

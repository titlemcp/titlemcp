# Razi Title MCP

Python MCP platform for title and real estate service operations. The project is structured as a reusable framework rather than a pile of tool scripts: MCP tools delegate into typed workflow services, workflow state is persisted behind repository interfaces, and county/state behavior is supplied through jurisdiction adapters or plugins.

## What Is Included

- FastMCP server with reusable title operations tools
- MCP client bridge for Ollama/local LLM function calling
- Pydantic domain schemas for workflows, audits, reviews, tasks, orders, and jurisdictions
- Async workflow engine with review-first state transitions
- In-memory repository for local development and tests
- Optional Postgres repository for durable JSONB workflow persistence
- Adapter registry with generic and Florida examples
- Plugin loading through Python entry points
- Structured JSON logging and lightweight trace spans
- Compatibility scripts: `demo_server.py`, `test_client.py`, and `app.py`

## Architecture

```text
MCP tools
  -> WorkflowService
    -> WorkflowEngine
      -> WorkflowRepository
      -> JurisdictionAdapter
```

The MCP layer is intentionally thin. Business state lives in `WorkflowRecord` models and repositories, so the same services can later be embedded into Django views, Celery tasks, or admin workflows.

Human review is first-class. The included workflows plan and track work, but they do not make autonomous legal or underwriting decisions.

## Jurisdiction Routing

Jurisdictions are modeled as `country`, `state`, `county`, and `municipality`. Routing resolves the
most specific adapter that supports both the jurisdiction and the workflow kind. For example:

- `US`, `MD`, `Baltimore`, `Baltimore City` routes public records searches to a Baltimore City adapter.
- `US`, `FL`, `Dade` or `Miami-Dade` routes public records searches to a Miami-Dade adapter.
- Other workflows in the same place can still fall back to state or generic adapters.

You can configure additional jurisdiction-specific adapters with JSON:

```bash
TITLE_MCP_JURISDICTION_CONFIG_PATH=docs/jurisdiction-adapters.example.json title-mcp-server
```

See [docs/jurisdiction-adapters.example.json](docs/jurisdiction-adapters.example.json) for the
shape of a configured adapter.

The repository also includes a generated `jurisdictions/` workspace so it is clear where new
country/state/county/municipality capabilities should live. See
[docs/JURISDICTION_STRUCTURE.md](docs/JURISDICTION_STRUCTURE.md) for the convention and refresh
command.

## Local Setup

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

For the existing local virtualenv in this project, you can run without reinstalling by setting `PYTHONPATH`:

```bash
PYTHONPATH=src .venv/bin/python -m title_mcp.mcp.server
```

## Install From A Package

After publishing, install with:

```bash
python -m pip install razi-title-mcp
```

Optional extras:

```bash
python -m pip install "razi-title-mcp[postgres]"
python -m pip install "razi-title-mcp[aws]"
```

## Run The MCP Server

Stdio transport, suitable for MCP clients:

```bash
title-mcp-server
```

HTTP transport:

```bash
TITLE_MCP_MCP_TRANSPORT=streamable-http title-mcp-server
```

When running from a source checkout without installing the package, the compatibility script still
works:

```bash
PYTHONPATH=src .venv/bin/python demo_server.py
```

## Try The Test Client

```bash
.venv/bin/python test_client.py
```

The client lists MCP tools and creates a municipal lien search workflow.

## Ollama Client

Make sure Ollama is running and the configured model is available, then run:

```bash
title-mcp-ollama
```

Or:

```bash
title-mcp-ollama \
  "Create an HOA estoppel workflow for file 2025-123 in Orange County, FL"
```

Set `TITLE_MCP_OLLAMA_MODEL` to change the model.

## State Backends

Local default:

```env
TITLE_MCP_STATE_BACKEND=memory
```

Postgres:

```env
TITLE_MCP_STATE_BACKEND=postgres
TITLE_MCP_POSTGRES_DSN=postgresql://title_mcp:title_mcp@localhost:5432/title_mcp
```

Install the Postgres extra for durable deployments:

```bash
.venv/bin/pip install -e ".[postgres]"
```

The Postgres repository creates a `title_mcp_workflows` table and stores auditable workflow records as JSONB.

## Extending Jurisdictions

Create an adapter that implements `JurisdictionAdapter`:

```python
from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind, WorkflowRequest


class MiamiDadePublicRecordsAdapter:
    adapter_id = "us-fl-miami-dade-public-records"
    priority = 150
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})
    scope = JurisdictionScope(country="US", state="FL", county="Miami-Dade")

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return self.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        ...
```

Adapters can be registered directly on `TitleMCPPlatform.adapters`, exposed through the
`title_mcp.adapters` entry point group, or loaded from `TITLE_MCP_JURISDICTION_CONFIG_PATH`.

## Tool Surface

The server exposes a generic `start_title_workflow` tool plus convenience tools:

- `analyze_document`
- `request_public_records_search`
- `request_hoa_estoppel`
- `request_municipal_lien_search`
- `request_tax_certificate`
- `track_release`
- `parse_payoff_letter`
- `generate_checklist_packet`
- `get_workflow_status`
- `list_workflows`
- `submit_human_review`

These wrappers all create normal workflow records, so private deployments can add or replace tools without changing the state model.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## Build And Publish

```bash
.venv/bin/pip install -e ".[publish]"
rm -rf dist build *.egg-info
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

See [docs/PUBLISHING.md](docs/PUBLISHING.md) for TestPyPI, PyPI, and trusted publishing notes.

The current package metadata is marked `LicenseRef-Proprietary` for private/commercial
distribution. Replace `LICENSE` and the `license` field in `pyproject.toml` before publishing as
open source.

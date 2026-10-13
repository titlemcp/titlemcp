# Getting Started

This guide runs TitleMCP from a git clone of the repository.

## Prerequisites

- Python 3.12 or newer
- A virtual environment
- Optional: Ollama running locally for the sample clients
- Optional: PACER credentials for live PACER bankruptcy searches
- Optional: a SerpAPI key for live HOA contact searches

## 1. Install

From a git clone of the repository:

```bash
./scripts/install.sh
```

It creates `.venv` and installs the core package and every platform and county
package into it, editable. Use a full clone rather than a ZIP download: the core
package reads its version from the repository's tags.

To install only the core, with the development tools:

```bash
python -m venv .venv
.venv/bin/pip install -e "packages/titlemcp[dev]"
```

## 2. Run The MCP Server

```bash
TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true .venv/bin/titlemcp-server
```

The default transport is stdio, which is the normal mode for MCP clients. Most
county packages register as plugins, which load only with
`TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`.

Connect Claude Code to it:

```bash
claude mcp add titlemcp -e TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true -- "$PWD/.venv/bin/titlemcp-server"
```

### Run It In Docker

```bash
docker compose up --build
```

The image has every package, with plugins loaded. Open the server catalog at
`http://localhost:8000/` or the MCP Inspector at `http://localhost:6274/`. The
catalog response includes `mcp.url` and an `inspector.url` with the backend
prefilled for Docker. The Dockerized Inspector also defaults to:

```text
Transport: Streamable HTTP
URL: http://titlemcp:8000/mcp
```

The Inspector proxy is bound to localhost by default. It requires a session token;
read the token from `docker compose logs mcp-inspector`. If you use the prefilled
URL printed by the container, replace `0.0.0.0` with `localhost` in your browser.
If the Inspector returns `Forbidden - invalid origin`, open it through
`http://localhost:6274/` or set `MCP_INSPECTOR_ALLOWED_ORIGINS` to include the
browser origin you are using.

The Inspector Resources tab includes `titlemcp://server/info`,
`titlemcp://server/runtime`, `titlemcp://tools/catalog`, and
`titlemcp://workflows/kinds`. The Prompts tab includes starter templates for
workflow intake, parcel lookup review, HOA contact review, and sample prompts
derived from the Ollama examples.

## 3. Run Tests

Core tests:

```bash
.venv/bin/python -m unittest discover -s packages/titlemcp/tests
```

A county or platform package's tests, for example Franklin County's recorder:

```bash
.venv/bin/python -m unittest discover -s packages/jurisdictions/us/oh/franklin/recorder/tests
```

## 4. Try A Sample

The easiest way to see an LLM trigger an MCP tool is with the Franklin County
Auditor Ollama sample. It asks a conversational parcel-search question and
verifies that the model chooses `franklin_county_auditor_search`.

Franklin County Auditor parcel search:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --scenario parcel \
  --parcel-id "010-000123-00"
```

HOA contact search:

```bash
python samples/hoa_serpapi_ollama/ollama_client.py \
  --hoa-name "Tartan Fields Homeowners Association" \
  --state Ohio
```

PACER business bankruptcy search:

```bash
python samples/pacer_ollama/ollama_client.py \
  --scenario business \
  --business-name "Example Holdings LLC"
```

Each sample logs:

- MCP server startup
- discovered tools
- the model-selected tool
- tool arguments
- MCP result summary

## 5. Understand The Output

TitleMCP tools usually return a `SourceResult`-style envelope:

```json
{
  "source_id": "us-oh-franklin-auditor",
  "status": "succeeded",
  "records": [],
  "citations": [],
  "warnings": [],
  "requires_human_review": true,
  "metadata": {}
}
```

The important fields are:

- `status`: `succeeded`, `no_results`, `requires_configuration`, or `failed`.
- `records`: canonical domain records.
- `citations`: source URLs and retrieval metadata.
- `warnings`: configuration or source errors.
- `requires_human_review`: defaults to true for title-impacting work.

## 6. Next Steps

- Configure live sources in [Configuration](CONFIGURATION.md).
- Read the current tool list in [Tool Reference](TOOLS.md).
- Try more examples in [Samples](SAMPLES.md).
- Learn how to add capabilities in [Extending TitleMCP](EXTENDING.md).

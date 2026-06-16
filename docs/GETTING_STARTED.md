# Getting Started

This guide assumes you are running TitleMCP from a local source checkout.

## Prerequisites

- Python 3.12 or newer
- A virtual environment
- Optional: Ollama running locally for the sample clients
- Optional: PACER credentials for live PACER bankruptcy searches
- Optional: a SerpAPI key for live HOA contact searches

## 1. Create The Environment

From the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -e "packages/titlemcp[dev]"
```

If you only need the core runtime:

```bash
.venv/bin/pip install -e packages/titlemcp
```

## 2. Run The MCP Server

From a source checkout:

```bash
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m title_mcp.mcp.server
```

After the package is installed, the console script is also available:

```bash
titlemcp-server
```

The default transport is stdio, which is the normal mode for MCP clients.

## 3. Run Tests

Core tests:

```bash
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover packages/titlemcp/tests
```

Franklin County jurisdiction package tests:

```bash
PYTHONPATH=packages/titlemcp/src:packages/jurisdictions/us/oh/franklin/recorder/src \
  .venv/bin/python -m unittest \
  packages/jurisdictions/us/oh/franklin/recorder/tests/test_contract.py
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

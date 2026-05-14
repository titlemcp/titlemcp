# Samples

The `samples/` folder contains runnable examples that start a local MCP server,
ask Ollama a natural-language question, and log whether the model chooses the
expected tool.

Install the core package first:

```bash
.venv/bin/pip install -e packages/titlemcp
```

Make sure Ollama is running and a tool-capable model is available.

## Regrid Parcel Lookup

```bash
python samples/regrid_ollama/ollama_client.py \
  --address "1150 Glenn Ave, Columbus, OH"
```

The prompt does not name `regrid_parcel_lookup`; the sample verifies that the
model chooses it. The tool returns `title_mcp.parcel_record`.

Useful debug flags:

```bash
TITLE_MCP_REGRID_TIMEOUT_SECONDS=3 \
TITLE_MCP_REGRID_COOKIE_TIMEOUT_SECONDS=3 \
TITLE_MCP_REGRID_MAX_PROXY_ATTEMPTS=2 \
python samples/regrid_ollama/ollama_client.py \
  --address "1150 Glenn Ave, Columbus, OH" \
  --tool-timeout 30
```

## PACER Bankruptcy Search

Business search:

```bash
python samples/pacer_ollama/ollama_client.py \
  --scenario business \
  --business-name "Example Holdings LLC"
```

Person search:

```bash
python samples/pacer_ollama/ollama_client.py \
  --scenario person \
  --first-name John \
  --last-name Smith
```

If credentials are missing, the tool should still be triggered and return
`requires_configuration`.

## Franklin County Auditor

Parcel search:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --scenario parcel \
  --parcel-id "030-000526-00"
```

Address search:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --scenario address \
  --address "1150 Glenn Ave"
```

This sample uses a wrapper server so the jurisdiction package can be loaded from
the source checkout.

## How To Read The Logs

Important log lines:

- `MCP tools discovered`: confirms the server exposed the expected tool.
- `Ollama requested tool`: confirms the model selected the tool.
- `Tool arguments`: shows what the model sent.
- `MCP result summary`: shows status, record count, warnings, and schema name.

The samples default to stopping after the MCP tool result. Pass
`--summarize-with-ollama` if you want the result sent back to the model for a
short narrative response.

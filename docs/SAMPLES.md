# Samples

The `samples/` folder contains runnable examples that start a local MCP server,
ask Ollama a natural-language question, and log whether the model chooses the
expected tool.

Install the core package first:

```bash
.venv/bin/pip install -e packages/titlemcp
```

Make sure Ollama is running and a tool-capable model is available.

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

The prompt does not name `franklin_county_auditor_search`; the sample verifies
that the model chooses it. The tool returns
`title_mcp.property_assessment_record` and preserves the raw Franklin Auditor
payload under `source_specific.franklin_auditor`.

This sample uses a wrapper server so the jurisdiction package can be loaded from
the source checkout.

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

## How To Read The Logs

Important log lines:

- `MCP tools discovered`: confirms the server exposed the expected tool.
- `Ollama requested tool`: confirms the model selected the tool.
- `Tool arguments`: shows what the model sent.
- `MCP result summary`: shows status, record count, warnings, and schema name.

The samples default to stopping after the MCP tool result. Pass
`--summarize-with-ollama` if you want the result sent back to the model for a
short narrative response.

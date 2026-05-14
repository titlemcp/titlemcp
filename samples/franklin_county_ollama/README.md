# Franklin County Auditor Ollama Sample

This sample starts a local MCP server with the Franklin County Auditor tool
registered, then asks Ollama a natural Franklin County auditor question. The
prompt does not name `franklin_county_auditor_search`; the sample is meant to
test whether the model chooses that MCP tool from context. The tool returns
canonical `title_mcp.property_assessment_record` data, so the default sample
stops after the MCP tool result instead of asking Ollama to summarize it.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- An Ollama model with tool-calling support, such as `qwen3`

Install the project dependencies from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/oh/franklin/recorder
```

Make sure the model is available:

```bash
ollama pull qwen3
```

## Run

From the repo root:

```bash
python samples/franklin_county_ollama/ollama_client.py --model qwen3
```

The default prompt asks conversationally for the Franklin County auditor record
for parcel `030-000526-00`. To search a different parcel:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --model qwen3 \
  --parcel-id 030-000526-00
```

You can also test address or owner prompts:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --model qwen3 \
  --scenario address \
  --address "1150 GLENN AVE"
```

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --model qwen3 \
  --scenario owner \
  --owner-name "ZWINK ROBERT V"
```

If Ollama answers without requesting the Franklin Auditor MCP tool, the sample
raises an error. That makes it useful as a tool-trigger smoke test.

For more verbose logs:

```bash
python samples/franklin_county_ollama/ollama_client.py --log-level DEBUG
```

The default behavior prints the canonical MCP tool result. To ask Ollama for a
natural-language summary after the canonical result comes back:

```bash
python samples/franklin_county_ollama/ollama_client.py \
  --model qwen3 \
  --summarize-with-ollama
```

For faster smoke tests, keep the default `--num-predict 512` and default
thinking-disabled mode. If you want a reasoning model to think before answering,
pass `--think`.

## What This Uses

- `franklin_auditor_mcp_server.py` starts the TitleMCP server over stdio and
  explicitly registers `FranklinAuditorToolset`.
- `ollama_client.py` connects to that stdio MCP server, exposes the Franklin
  tool to Ollama, executes the model-requested tool call, and prints the
  canonical tool result. Passing `--summarize-with-ollama` sends the canonical
  result back to the model for a final answer.

The server wrapper sets `PYTHONPATH` for the local checkout so the sample works
while developing, even before the Franklin County package is published.

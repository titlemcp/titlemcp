# Montgomery County Auditor Ollama Sample

This sample starts a local MCP server with the Montgomery County Auditor tool
registered, then asks Ollama a natural Montgomery County auditor question. The
prompt does not name `montgomery_county_auditor_search`; the sample is meant to
test whether the model chooses that MCP tool from context. The tool returns
canonical `title_mcp.property_assessment_record` data, so the default sample
stops after the MCP tool result instead of asking Ollama to summarize it.

Montgomery County runs the same Tyler iasWorld platform as Franklin and Clermont,
so the tool is a config entry in `titlemcp-us-oh-auditor` backed by the shared
`titlemcp-platform-iasworld` scraper. Its parcel IDs are alphanumeric (example
`A01 00000 0001`), so the default parcel scenario uses one.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- An Ollama model with tool-calling support, such as `qwen3`

Install the project dependencies from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/iasworld
python -m pip install -e packages/jurisdictions/us/oh/auditor
```

Make sure the model is available:

```bash
ollama pull qwen3
```

## Run

From the repo root:

```bash
python samples/montgomery_auditor_ollama/ollama_client.py --model qwen3
```

The default prompt asks conversationally for the Montgomery County auditor record
for parcel `A01 00000 0001`. To search a different parcel:

```bash
python samples/montgomery_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --parcel-id "A01 00000 0001"
```

You can also test address or owner prompts:

```bash
python samples/montgomery_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --scenario address \
  --address "100 EXAMPLE AVE"
```

```bash
python samples/montgomery_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --scenario owner \
  --owner-name "DOE JANE A"
```

If Ollama answers without requesting the Montgomery Auditor MCP tool, the sample
raises an error. That makes it useful as a tool-trigger smoke test.

For more verbose logs:

```bash
python samples/montgomery_auditor_ollama/ollama_client.py --log-level DEBUG
```

The default behavior prints the canonical MCP tool result. To ask Ollama for a
natural-language summary after the canonical result comes back:

```bash
python samples/montgomery_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --summarize-with-ollama
```

For faster smoke tests, keep the default `--num-predict 512` and default
thinking-disabled mode. If you want a reasoning model to think before answering,
pass `--think`.

## What This Uses

- `ollama_client.py` starts the standard `title_mcp.mcp.server` stdio server
  through the shared sample helper, exposes the Montgomery tool to Ollama,
  executes the model-requested tool call, and prints the canonical tool result.
  Passing `--summarize-with-ollama` sends the canonical result back to the model
  for a final answer.

The Montgomery Auditor tool is loaded from the `titlemcp-us-oh-auditor`
package's `title_mcp.toolsets` entry point. Install that package and the shared
`titlemcp-platform-iasworld` package in editable mode while developing so the
standard server can discover the tool from the local checkout.

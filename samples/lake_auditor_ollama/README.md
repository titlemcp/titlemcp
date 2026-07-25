# Lake County Auditor Ollama Sample

This sample starts a local MCP server with the Lake County Auditor tool
registered, then asks Ollama a natural Lake County auditor question. The prompt
does not name `lake_county_auditor_search`; the sample is meant to test whether
the model chooses that MCP tool from context. The tool returns canonical
`title_mcp.property_assessment_record` data, so the default sample stops after the
MCP tool result instead of asking Ollama to summarize it.

Lake County's auditor site identifies as Tyler **iasWorld** but serves a single
unified **`realprop`** Basic Search for parcel, owner, and address. Two config
knobs on the shared `titlemcp-platform-iasworld` make it work: a `mode_map` that
routes every mode to the `realprop` URL, and `form_field_overrides` that rename
the two POST fields whose names differ on that form (`inpNumber` -> `inpNo`,
`inpOwner` -> `inpOwner1`). Lake's datalet **detail** layout is a third variant
that the shared profiles do not yet fully parse, so search and the header-derived
canonical fields (parcel, owner, site address, token) populate while deep detail
extraction is a known follow-up — Lake is **NEEDS-VERIFICATION**, not fully
enabled. See [`docs/OHIO_AUDITOR_EXPANSION.md`](../../docs/OHIO_AUDITOR_EXPANSION.md).

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
python samples/lake_auditor_ollama/ollama_client.py --model qwen3
```

The default prompt asks conversationally for the Lake County auditor record for
a parcel. To search a different parcel:

```bash
python samples/lake_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --parcel-id 00A0000000002
```

You can also test address or owner prompts:

```bash
python samples/lake_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --scenario address \
  --address "100 EXAMPLE ST"
```

```bash
python samples/lake_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --scenario owner \
  --owner-name "DOE JANE A"
```

If Ollama answers without requesting the Lake Auditor MCP tool, the sample
raises an error. That makes it useful as a tool-trigger smoke test.

For more verbose logs:

```bash
python samples/lake_auditor_ollama/ollama_client.py --log-level DEBUG
```

The default behavior prints the canonical MCP tool result. To ask Ollama for a
natural-language summary after the canonical result comes back:

```bash
python samples/lake_auditor_ollama/ollama_client.py \
  --model qwen3 \
  --summarize-with-ollama
```

For faster smoke tests, keep the default `--num-predict 512` and default
thinking-disabled mode. If you want a reasoning model to think before answering,
pass `--think`.

## What This Uses

- `ollama_client.py` starts the standard `title_mcp.mcp.server` stdio server
  through the shared sample helper, exposes the Lake tool to Ollama, executes
  the model-requested tool call, and prints the canonical tool result. Passing
  `--summarize-with-ollama` sends the canonical result back to the model for a
  final answer.

The Lake Auditor tool is loaded from the `titlemcp-us-oh-auditor` package's
`title_mcp.toolsets` entry point. Install that package (and the shared iasWorld
platform) in editable mode while developing so the standard server can discover
it from the local checkout.

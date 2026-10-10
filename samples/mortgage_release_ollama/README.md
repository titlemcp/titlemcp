# Mortgage Release Search Ollama Sample

This sample starts the local TitleMCP server, asks Ollama whether a paid-off
mortgage has been released, and exposes only `mortgage_release_search` to the
model. The prompt does not name the tool; the sample logs whether Ollama chooses
it.

The default behavior prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`

Install the core package and the Ohio recorder package from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/jurisdictions/us/oh/recorder
```

No credentials are needed: the counties' public indexes issue a session to
anyone who asks. Without the Ohio recorder package installed, the tool is still
triggered and returns `requires_configuration`, naming the county it has no
recorder for.

## Run

From the repo root:

```bash
python samples/mortgage_release_ollama/ollama_client.py --model qwen3
```

The default instrument number is invented, so the record comes back
`mortgage_not_found`. Pass a mortgage's number from a commitment to see a real
answer:

```bash
python samples/mortgage_release_ollama/ollama_client.py \
  --county Stark \
  --instrument "<the mortgage's instrument number>" \
  --paid-off-on 2026-05-01 \
  --summarize-with-ollama
```

The tool returns `title_mcp.mortgage_release_search`: the mortgage, each release
found with the basis for the match (the county's own link, the release's text
citing the mortgage, or only the same parties), and notes for the reviewer.

# OFAC Sanctions Screening Ollama Sample

This sample starts the local TitleMCP server, asks Ollama a natural question about
screening a closing file's parties, and exposes only `ofac_screen_parties` to the
model. The prompt does not name the tool; the sample logs whether Ollama chooses it.

The default behavior prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally, with a tool-calling model such as `qwen3`
- Network access to `sanctionslistservice.ofac.treas.gov` on the first run (no
  credentials: OFAC's lists are public). Lists are cached in
  `TITLE_MCP_OFAC_CACHE_DIR` (default `~/.cache/titlemcp/ofac`) and refreshed daily.

```bash
python -m pip install -e packages/titlemcp
```

## Run

From the repo root:

```bash
python samples/ofac_ollama/ollama_client.py --model qwen3
python samples/ofac_ollama/ollama_client.py --seller "<a name copied from OFAC's SDN list>" --summarize-with-ollama
```

The default parties are invented, so they come back as `no_match`. To see a
`potential_match` with the reasons for its score, pass a name copied from OFAC's
published SDN list with `--seller`.

Without network access and with no cached lists, the tool returns `failed` with a
warning explaining where the lists come from.

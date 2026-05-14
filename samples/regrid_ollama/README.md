# Regrid Parcel Lookup Ollama Sample

This sample starts the local TitleMCP server, asks Ollama a natural parcel
lookup question, and exposes only `regrid_parcel_lookup` to the model. The
prompt does not name the tool; the sample logs whether Ollama chooses it.

The default behavior prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.
The MCP result is a canonical `title_mcp.parcel_record`; Regrid's original
response fields remain available under `source_specific.regrid`.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`
- Regrid smart proxy configuration

Install the project dependencies from the repo root:

```bash
python -m pip install -e packages/titlemcp
```

Configure smart proxy in `.env` or the process environment:

```env
TITLE_MCP_SMART_PROXY=user:password@proxy.example.com
TITLE_MCP_REGRID_PROXY_PORT_START=10001
TITLE_MCP_REGRID_PROXY_PORT_END=10999
TITLE_MCP_REGRID_MAX_PROXY_ATTEMPTS=10
```

The legacy `SMART_PROXY` variable is also supported. Increase
`TITLE_MCP_REGRID_MAX_PROXY_ATTEMPTS` only if your proxy pool needs more rotation before a request
succeeds.

## Run

From the repo root:

```bash
python samples/regrid_ollama/ollama_client.py --model qwen3
```

Use a different address:

```bash
python samples/regrid_ollama/ollama_client.py \
  --model qwen3 \
  --address "1150 Glenn Ave, Columbus, OH"
```

The sample defaults to a 90 second MCP tool timeout so proxy/network issues fail visibly:

```bash
python samples/regrid_ollama/ollama_client.py \
  --address "1150 Glenn Ave, Columbus, OH" \
  --tool-timeout 120
```

If the smart proxy is not configured, the sample should still prove the tool was
triggered, then return `requires_configuration` from the MCP tool.

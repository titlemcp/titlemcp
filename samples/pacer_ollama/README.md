# PACER Bankruptcy Search Ollama Sample

This sample starts the local TitleMCP server, asks Ollama a natural bankruptcy
search question, and exposes only `pacer_bankruptcy_search` to the model. The
prompt does not name the tool; the sample logs whether Ollama chooses it.

The default behavior prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`
- PACER Case Locator API credentials

Install the project dependencies from the repo root:

```bash
python -m pip install -e packages/titlemcp
```

Configure credentials in `.env` or the process environment:

```env
TITLE_MCP_PACER_USERNAME=
TITLE_MCP_PACER_PASSWORD=
TITLE_MCP_PACER_CLIENT_CODE=
TITLE_MCP_PACER_QA_MODE=true
```

Use QA credentials and `TITLE_MCP_PACER_QA_MODE=true` for non-billable testing.
Production PACER searches may be billable.

## Run

From the repo root:

```bash
python samples/pacer_ollama/ollama_client.py --model qwen3
```

Run a business/entity prompt:

```bash
python samples/pacer_ollama/ollama_client.py \
  --model qwen3 \
  --scenario business \
  --business-name "Example Holdings LLC"
```

The sample defaults to a 90 second MCP tool timeout:

```bash
python samples/pacer_ollama/ollama_client.py \
  --scenario business \
  --business-name "Example Holdings LLC" \
  --tool-timeout 120
```

If PACER credentials are not configured, the sample should still prove the tool
was triggered, then return `requires_configuration` from the MCP tool.

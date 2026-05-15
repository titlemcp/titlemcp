# HOA Contact Search Ollama Sample

This sample starts the local TitleMCP server, asks Ollama a natural HOA contact
lookup question, and exposes only `hoa_contact_search` to the model. The prompt
does not name the tool; the sample logs whether Ollama chooses it.

The MCP tool runs a SerpAPI Google search, picks the top result, fetches that
page with a Python-native HTTP client (`urllib`) and parses out the visible
text with `html.parser`. The cleaned page text is returned to Ollama under
`records[0].first_result_page.text` so the model can extract structured HOA
contact details (mailing address, phone, email, website, management company)
from the live page rather than from search snippets alone.

By default the sample asks Ollama to read that page text and return a JSON
contact record. Pass `--no-extract-with-ollama` to stop after the MCP tool
returns and dump the raw record instead.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`
- A SerpAPI key for live Google search results

Install the project dependencies from the repo root:

```bash
python -m pip install -e packages/titlemcp
```

Configure the SerpAPI key in `.env` or the process environment:

```env
TITLE_MCP_SERPAPI_API_KEY=
TITLE_MCP_SERPAPI_TIMEOUT_SECONDS=30
```

If the key is not configured, the sample should still prove the tool was
triggered, then return `requires_configuration` from the MCP tool.

## Run

From the repo root:

```bash
python samples/hoa_serpapi_ollama/ollama_client.py --model qwen3
```

Search for a specific HOA:

```bash
python samples/hoa_serpapi_ollama/ollama_client.py \
  --model qwen3 \
  --hoa-name "Tartan Fields Homeowners Association" \
  --state Ohio
```

Omit the state by passing an empty value:

```bash
python samples/hoa_serpapi_ollama/ollama_client.py \
  --hoa-name "Example Woods HOA" \
  --state ""
```

The sample defaults to a 60 second MCP tool timeout:

```bash
python samples/hoa_serpapi_ollama/ollama_client.py \
  --hoa-name "Tartan Fields Homeowners Association" \
  --state Ohio \
  --tool-timeout 90
```

## Output

The tool returns a canonical `title_mcp.hoa_contact_search` record with
candidate websites, addresses, phone numbers, and email addresses when available
from Google search results. It first looks for the likely official HOA domain,
then uses a second `site:<domain>` search to find contact, management,
assessment, payment, and board pages on that domain. Raw candidate evidence is
preserved under each candidate and SerpAPI metadata is preserved under
`source_specific.serpapi`.

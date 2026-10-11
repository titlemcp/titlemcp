# Property Tax Status Search Ollama Sample

This sample starts the local TitleMCP server and asks Ollama whether a parcel's
property taxes are paid. It exposes only `property_tax_status_search` to the
model. The prompt doesn't name the tool; the sample logs whether Ollama chooses
it.

By default the sample prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`

Install the core package and a tax package from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/dc/tax
```

No credentials are needed: the District publishes its tax extract as open data.
Without a tax package for the county installed, the tool is still triggered. It
returns `requires_configuration`, naming the county it has no tax connector for.

## Run

From the repo root:

```bash
python samples/property_tax_ollama/ollama_client.py --model qwen3
```

The default parcel is invented, so the record comes back `parcel_not_found`.
Pass a real parcel to see an answer:

```bash
python samples/property_tax_ollama/ollama_client.py \
  --parcel "<square and lot>" \
  --summarize-with-ollama
```

Ohio parcels work the same way with the Ohio auditor package installed:

```bash
python samples/property_tax_ollama/ollama_client.py \
  --state OH --county Franklin --parcel "<parcel number>"
```

The tool returns a `title_mcp.property_tax_status` record. It has:
- each tax year's billed, paid and balance amounts;
- installments, where the collector shows them;
- `paid`, `due` or `past_due`;
- the date of the collector's data;
- notes for the reviewer.

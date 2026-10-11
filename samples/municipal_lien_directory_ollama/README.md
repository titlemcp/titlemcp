# Municipal Lien Directory Ollama Sample

This sample starts the local TitleMCP server and asks Ollama how to order a
city's municipal lien search. It exposes only `municipal_lien_directory` to the
model. The prompt doesn't name the tool; the sample logs whether Ollama chooses
it.

By default the sample prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`

Install the core package and the Florida directory from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/fl/municipal
```

No credentials are needed: the directory is packaged data. Without a directory
for the state installed, the tool is still triggered. It returns
`requires_configuration`, naming the county it has no directory for.

## Run

From the repo root:

```bash
python samples/municipal_lien_directory_ollama/ollama_client.py --model qwen3
```

Ask about another city, or a county's unincorporated area:

```bash
python samples/municipal_lien_directory_ollama/ollama_client.py \
  --county Pinellas --city Clearwater --summarize-with-ollama
```

The tool returns a `title_mcp.municipal_lien_directory` record with an entry for
the city and one for the county. Each has:
- who issues the lien letter, how to order it, the fee and the turnaround;
- what the letter covers and excludes;
- the permit and code case searches;
- the water, sewer, solid waste and stormwater providers;
- how special assessments are billed.

# Release Tracking Status Ollama Sample

This sample starts the local TitleMCP server and asks Ollama whether a lender is
late recording the release of a paid-off mortgage. It exposes only
`release_tracking_status` to the model. The prompt doesn't name the tool; the
sample logs whether Ollama chooses it.

By default the sample prints the MCP tool result and stops. Pass
`--summarize-with-ollama` to send the result back to Ollama for a final summary.

## Prerequisites

- Python 3.12 or newer
- Ollama running locally
- A tool-calling Ollama model, such as `qwen3`

Install the core package and the Ohio recorder package from the repo root:

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/platforms/countyfusion
python -m pip install -e packages/jurisdictions/us/oh/recorder
```

No credentials are needed. Without the Ohio recorder package installed, the tool
is still triggered: it returns `partial`, with a record whose status is
`not_checked`, giving Ohio's deadline and the date to check the county's records
by hand.

## Run

From the repo root:

```bash
python samples/release_tracking_ollama/ollama_client.py --model qwen3
```

The default instrument number is invented, so the county's index doesn't find
the mortgage and the record comes back `needs_review`. Pass a mortgage's number
from a commitment to see a real answer:

```bash
python samples/release_tracking_ollama/ollama_client.py \
  --county Stark \
  --instrument "<the mortgage's instrument number>" \
  --paid-off-on 2026-05-01 \
  --summarize-with-ollama
```

The tool returns a `title_mcp.release_tracking_status` record. It has:
- the state's deadline, with its statute citation;
- the date the release is due;
- `released`, `released_late`, `awaiting_release`, `overdue`, `not_released`,
  `needs_review` or `not_checked`;
- when to look again, and the next step;
- the county index's own answer, for review.

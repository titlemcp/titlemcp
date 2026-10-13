# TitleMCP

[![CI](https://github.com/titlemcp/titlemcp/actions/workflows/ci.yml/badge.svg)](https://github.com/titlemcp/titlemcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/titlemcp)](https://pypi.org/project/titlemcp/)
[![Python](https://img.shields.io/pypi/pyversions/titlemcp)](https://pypi.org/project/titlemcp/)

**Title research tools for AI agents.** TitleMCP connects Claude, or any
[MCP](https://modelcontextprotocol.io) client or local model, to county
recorders, tax collectors, state statutes and federal sanctions lists. Your
agent can then do the lookups a title file needs and show where each answer
came from.

Every title file means the same chores. Search the recorder's index, pull the
tax status, find out which office issues the lien letter, screen the parties,
and chase the lender for the release. Every county runs them on a different
website. TitleMCP turns those chores into tools an agent can call, and returns
structured answers it can act on. It's built for title agents, escrow and
closing teams, real estate attorneys, and the developers building agents for
them.

Ask it things like:

- *"The Alex Example mortgage in Dallas County was paid off May 1. Has the
  release recorded yet? Is the lender late?"*
- *"We paid off the Alex Example loan in Cuyahoga County on March 3. If the
  release still isn't recorded, what can we do?"*
- *"Are the taxes paid on this Fairfax County parcel?"*
- *"Who do I order a municipal lien search from in Fort Lauderdale, and what does
  it cost?"*
- *"Screen the buyers and sellers on this file against OFAC."*

Each question is answered from the source itself: the recorder's index, the
collector's own records, the statute's official text. The tool's answer carries
links to those sources.

## Why it's different

- **It reads the source.** Tax status comes straight from the county
  collector's website. Release checks read the recorder's index, and deadlines
  come from the statute itself.
- **It knows the law it checks against.** Release deadlines are on file for 44
  states and DC. Each is read from the statute, with the sentence that sets it,
  a link to the official text, and the remedy once the lender is late. Where
  the statute gives one, it also gives the route for clearing the lien
  without the lender.
- **Its accuracy is measured.** OFAC screening handles transliterations,
  typos, reordered names and initials. It keeps common names quiet.
  [The benchmark](scripts/ofac_benchmark.py) uses 3,000 disguised real listings
  and 3,000 realistic U.S. names. Screening surfaces **97.6%** of the listings
  with **no false alarms**. Whole-name fuzzy matching, the usual approach,
  manages 75.0% at the same zero false alarms. Every screening returns a
  receipt showing a "no match" was searched for properly.
- **A person stays in charge.** Answers that affect title are marked for review.
  The tools find and report facts; they never make the legal or underwriting
  decision.
- **Most tools need no account.** The county tools, OFAC screening, the
  deadlines and the municipal directory need no API key and no sign-up.

## What it covers

| Lookup | Where |
| --- | --- |
| **Has the mortgage been released?** (county recorder index) | **TX:** Bexar, Collin, Dallas, Denton, Hidalgo, Montgomery, Tarrant · **OH:** Ashland, Cuyahoga, Stark, Wayne · **CO:** Arapahoe · **IL:** Lake · **PA:** Delaware · **SC:** Greenville |
| **Is the lender late?** (statutory release deadlines) | 44 states and DC |
| **Are the property taxes paid?** | **DC** · **OH:** Butler, Clermont, Franklin, Lake, Lucas, Montgomery · **CA:** Contra Costa · **IL:** DuPage · **NM:** Bernalillo · **PA:** Delaware · **TN:** Shelby · **VA:** Fairfax |
| **Who issues the municipal lien letter?** Plus permits, code cases, utilities and assessments | **FL:** all 67 counties and the 120 cities of 20,000 people or more, about 94% of Floridians |
| **Auditor property search** | **OH:** Butler, Clermont, Franklin, Lake, Lucas, Montgomery |
| **The recorded chain for one parcel** | **OH:** Franklin |
| **OFAC sanctions screening** | Nationwide: Treasury's SDN and consolidated lists, refreshed daily |
| **Bankruptcy, HOA contacts, parcel data** | Nationwide, with your own PACER, SerpAPI or proxy account |

Don't see your county? Counties on the same records software share a platform
package (PublicSearch, CountyFusion, iasWorld), so adding the next county on one
is mostly a matter of describing its site. See [Add your county](#add-your-county).

## Get started

### With Docker

```bash
git clone https://github.com/titlemcp/titlemcp
cd titlemcp
docker compose up --build
```

The server is now at `http://localhost:8000/mcp`. Add it to Claude Code:

```bash
claude mcp add --transport http titlemcp http://localhost:8000/mcp
```

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) also runs at
`http://localhost:6274` for calling tools by hand. Its sign-in token is in
`docker compose logs mcp-inspector`.

### With Python 3.12 or newer

```bash
git clone https://github.com/titlemcp/titlemcp
cd titlemcp
./scripts/install.sh
```

The script installs TitleMCP and every county package into `.venv`. It then
prints the command for Claude Code and the snippet for Claude Desktop's config,
with your path filled in:

```bash
claude mcp add titlemcp -e TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true -- "$PWD/.venv/bin/titlemcp-server"
```

Use `git clone`, not *Download ZIP*: the package reads its version from the
repository's tags.

### In the cloud

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/titlemcp/titlemcp)
[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy?template=https://github.com/titlemcp/titlemcp)
[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run?git_repo=https://github.com/titlemcp/titlemcp)
[![Deploy to DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/titlemcp/titlemcp/tree/main)
[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=git&repository=github.com/titlemcp/titlemcp&branch=main&builder=dockerfile&name=titlemcp&ports=8000;http;/&env%5BPORT%5D=8000)

Each button builds the same Docker image, with every county package, and serves
MCP at `https://<your-app>/mcp`. **The server has no sign-in**, so anyone with
the URL can call it. Read [Deploying](docs/DEPLOY.md) before you add any
credentials.

### Then ask

Start with *"What can TitleMCP look up?"*, then try the questions at the top of
this page.

## What an answer looks like

*"We paid off the Alex Example mortgage in Orange County, Florida on June 1.
When is the release due?"* Orange County has no recorder connector yet, so the
tool can't check the index itself. It still knows Florida's deadline, and its
answer includes:

```json
{
  "status": "not_checked",
  "paid_off_on": "2026-06-01",
  "release_due_on": "2026-07-31",
  "deadline": {
    "days": 60,
    "clock_start": "payoff",
    "citation": "Fla. Stat. § 701.04(2)(a)",
    "remedy": "Prevailing party in a civil action to enforce the release duty gets reasonable attorney fees and costs. No statutory damages amount.",
    "alternative_release": "Title insurer officer or appointed agent may record a certificate of release if none is recorded after payoff per estoppel letter; copy to servicer. No wait stated. Loans <= $500,000, not open-end.",
    "alternative_citation": "Fla. Stat. § 701.041"
  },
  "next_action": "No connector reads Orange County's index. Check its records by hand after 2026-07-31, the deadline.",
  "requires_human_review": true
}
```

In a county with a connector, such as Dallas, the tool also reads the index.
The status is then one of `released`, `released_late`, `awaiting_release`,
`overdue`, `not_released` or `needs_review`, with what the index showed.

## The tools

| Tool | What it does | Needs |
| --- | --- | --- |
| `mortgage_release_search` | Finds one mortgage's release in the county recorder's index | — |
| `release_tracking_status` | Judges that release against the state's deadline: on time, late or overdue | — |
| `property_tax_status_search` | Reads a parcel's current tax status from the collector | — |
| `municipal_lien_directory` | Says who issues the lien letter and how to order it, and where permits and code cases are | — |
| `ofac_screen_parties` | Screens people and companies against OFAC's lists, with a receipt | — |
| `ofac_list_status` | Shows which list publication screening is using | — |
| `<county>_auditor_search` | Searches an Ohio county auditor by parcel, owner or address | — |
| `pacer_bankruptcy_search` | Searches PACER's bankruptcy party index | A PACER account (PACER bills searches) |
| `hoa_contact_search` | Finds an HOA's contacts from the web | A SerpAPI key |
| `parcel_lookup` | Looks up parcel data by address | A proxy, see [Configuration](docs/CONFIGURATION.md#parcel-provider) |

There are also workflow tools: `start_title_workflow`, `request_tax_certificate`,
`request_hoa_estoppel`, `request_municipal_lien_search`, `track_release`,
`parse_payoff_letter`, `generate_checklist_packet` and others. Each records a
piece of work with its tasks, audit trail and a human review step, and can
optionally be stored in Postgres. They plan and track the work but don't place
vendor orders themselves. The [tool reference](docs/TOOLS.md) has every tool's
inputs and outputs.

## Run it with a local model

TitleMCP doesn't depend on a hosted AI. The lookup tools have
[runnable samples](docs/SAMPLES.md). Each one starts the server and asks a
local [Ollama](https://ollama.com) model a plain question, and the model has to
pick the right tool by itself.

## Add your county

A county is a small Python package that registers through entry points. If the
county runs software TitleMCP already reads, its package is mostly a
description of the county's site. Start from
[Extending TitleMCP](docs/EXTENDING.md) and the
[package template](packages/titlemcp/templates/jurisdiction-package/). Then read
[CONTRIBUTING.md](CONTRIBUTING.md) for how to open a pull request.

If you need a county and can't build it yourself, open an issue that names it.

## Documentation

- [Getting started](docs/GETTING_STARTED.md): the source checkout, tests and samples
- [Tool reference](docs/TOOLS.md): every tool's inputs and outputs
- [Configuration](docs/CONFIGURATION.md): every setting
- [Deploying](docs/DEPLOY.md): the cloud buttons and connecting a client
- [Extending TitleMCP](docs/EXTENDING.md): adapters, connectors and county packages
- [AGENTS.md](AGENTS.md): conventions for contributors and coding agents
- [Architecture](packages/titlemcp/docs/ARCHITECTURE.md)

## License

See [LICENSE](LICENSE).

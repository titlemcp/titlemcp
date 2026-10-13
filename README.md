# TitleMCP

[![PyPI](https://img.shields.io/pypi/v/titlemcp)](https://pypi.org/project/titlemcp/)
[![CI](https://github.com/titlemcp/titlemcp/actions/workflows/ci.yml/badge.svg)](https://github.com/titlemcp/titlemcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

TitleMCP is an open-source [MCP](https://modelcontextprotocol.io) server that
gives AI assistants tools for title and real estate work. An assistant can ask
whether a mortgage was released, whether a parcel's taxes are paid, or whether a
buyer appears on OFAC's sanctions lists. It gets back structured answers read
from the public record, with the source cited. Every answer that bears on title
is flagged for a person to review: the tools report facts and leave the
decisions to you.

## What works today

**No account or key needed:**

| Tool | What it answers | Coverage |
| --- | --- | --- |
| [`ofac_screen_parties`](docs/TOOLS.md#ofac_screen_parties) | Is this person or company on OFAC's SDN or Consolidated list? Returns a receipt that lists near misses too. | Nationwide. Uses OFAC's public lists, refreshed daily. |
| [`mortgage_release_search`](docs/TOOLS.md#mortgage_release_search) | Has this mortgage or deed of trust been released of record? | 15 counties in 6 states ([below](#county-coverage)) |
| [`release_tracking_status`](docs/TOOLS.md#release_tracking_status) | After a payoff, is the release recorded, and was it recorded within the state's deadline? | Deadlines for 44 states and DC. Recorded or not is checked in the release-search counties. |
| [`property_tax_status_search`](docs/TOOLS.md#property_tax_status_search) | Are this parcel's property taxes paid, due or delinquent? | 13 collectors in 7 states and DC ([below](#county-coverage)) |
| [`municipal_lien_directory`](docs/TOOLS.md#municipal_lien_directory) | Who issues lien letters for this parcel, and where are its permits and code cases? | Florida: all 67 counties and the 120 cities of 20,000 people or more |
| [`<county>_auditor_search`](docs/TOOLS.md#franklin_county_auditor_search) | Owner, parcel and values from the county auditor | Ohio: Butler, Clermont, Franklin, Lake, Lucas and Montgomery |

**With your own credentials** ([how to set them](docs/CONFIGURATION.md#credentials)):

| Tool | What it answers | Needs |
| --- | --- | --- |
| [`pacer_bankruptcy_search`](docs/TOOLS.md#pacer_bankruptcy_search) | Bankruptcy cases naming a person or business, nationwide | A PACER account. Searches can be billed to it. |
| [`hoa_contact_search`](docs/TOOLS.md#hoa_contact_search) | Contact candidates for an HOA or its management company | A SerpAPI key |
| [`parcel_lookup`](docs/TOOLS.md#parcel_lookup) | The Regrid parcel record for an address | A rotating proxy |

**Workflow tools.** `start_title_workflow`, `request_hoa_estoppel`,
`request_municipal_lien_search`, `request_tax_certificate`,
`request_public_records_search`, `track_release`, `analyze_document`,
`parse_payoff_letter` and `generate_checklist_packet` record a title task with the
steps its jurisdiction needs. `get_workflow_status`, `list_workflows` and
`submit_human_review` follow it through review, with an audit trail. These tools
plan and track the work. They don't yet order estoppels, run OCR or read payoff
letters.

`list_title_capabilities`, `list_source_connectors` and `list_vendor_connectors`
report what a running server has installed.

Outside its coverage, a tool answers `requires_configuration` and names what is
missing rather than guessing.

### County coverage

| State | Release search | Property tax status |
| --- | --- | --- |
| California | | Contra Costa |
| Colorado | Arapahoe | |
| District of Columbia | | The District |
| Illinois | Lake | DuPage |
| New Mexico | | Bernalillo |
| Ohio | Ashland, Cuyahoga, Stark, Wayne | Butler, Clermont, Franklin, Lake, Lucas, Montgomery |
| Pennsylvania | Delaware | Delaware (county tax) |
| South Carolina | Greenville | |
| Tennessee | | Shelby (county tax) |
| Texas | Bexar, Collin, Dallas, Denton, Hidalgo, Montgomery, Tarrant | |
| Virginia | | Fairfax |

Each county is a small package. Adding one is described in
[Extending TitleMCP](docs/EXTENDING.md), and most counties on a platform that
TitleMCP already reads (Kofile PublicSearch, Kofile CountyFusion, Tyler iasWorld)
need only a configuration entry and a test.

## Try it

You need Python 3.12 or newer, and no accounts or keys.

```bash
git clone https://github.com/titlemcp/titlemcp && cd titlemcp
python3.12 -m venv .venv && . .venv/bin/activate
pip install $(find packages -name pyproject.toml -not -path '*/templates/*' -exec dirname {} \;)
```

That installs the core and every county package. The county packages load as
plugins, which are off by default, so turn them on when you connect a client:

```bash
# Claude Code
claude mcp add titlemcp -e TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true -- "$PWD/.venv/bin/titlemcp-server"

# or MCP Inspector, in the browser
npx @modelcontextprotocol/inspector -e TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true -- .venv/bin/titlemcp-server
```

Then ask something like *"Who handles municipal lien letters for St. Petersburg,
Florida?"* or *"Screen Example Holdings LLC against OFAC."* The first OFAC
screening downloads the lists, which takes a few seconds.

`pip install titlemcp` installs only the core from PyPI: OFAC screening, the
release deadlines, the workflow tools and the credentialed tools. The county
packages install from this repository.

## Deploy your own

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/titlemcp/titlemcp)
[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy?template=https://github.com/titlemcp/titlemcp)
[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run?git_repo=https://github.com/titlemcp/titlemcp)
[![Deploy to DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/titlemcp/titlemcp/tree/main)
[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=git&repository=github.com/titlemcp/titlemcp&branch=main&builder=dockerfile&name=titlemcp&ports=8000;http;/&env%5BPORT%5D=8000)

Each button builds this repository's Docker image and serves MCP at
`https://<your-app>/mcp`. The image runs the core tools; the county packages
listed above aren't in it yet. The server has no sign-in of its own, so read
[Deploying](docs/DEPLOY.md) before you add credentials to a public deployment.

## Credentials

Only the three tools above that name a credential need one. Their variables are
listed in [`.env.example`](.env.example). Keep them in a secret manager, a local
`.env`, your MCP client's configuration or your host's settings.
[Configuration](docs/CONFIGURATION.md#credentials) explains each option and how
the code keeps them out of logs.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [Tool reference](docs/TOOLS.md): every tool, its input and what it returns
- [Configuration](docs/CONFIGURATION.md)
- [Deploying](docs/DEPLOY.md)
- [Samples](docs/SAMPLES.md): Ollama clients that show a model choosing each tool
- [Extending TitleMCP](docs/EXTENDING.md): adding a county, source or vendor
- [Architecture](packages/titlemcp/docs/ARCHITECTURE.md),
  [jurisdiction packages](packages/titlemcp/docs/JURISDICTION_PACKAGES.md) and
  [publishing](packages/titlemcp/docs/PUBLISHING.md)
- [Agent and contributor guide](AGENTS.md)

## Repository layout

```text
packages/
  titlemcp/                  core: the server, core tools, domain records (PyPI: titlemcp)
  platforms/                 shared clients for county software
    publicsearch/            Kofile PublicSearch recorders
    countyfusion/            Kofile CountyFusion recorders
    iasworld/                Tyler iasWorld auditors and tax collectors
  jurisdictions/us/<state>/  one package per state and record type, e.g.
    tx/recorder/             titlemcp-us-tx-recorder
    fl/municipal/            titlemcp-us-fl-municipal
jurisdiction-catalog/        generated geography reference, not package code
samples/                     runnable Ollama examples, one per tool
```

## Development

Install the core with its development tools and run its tests:

```bash
.venv/bin/pip install -e "packages/titlemcp[dev]"
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover \
  -s packages/titlemcp/tests -v
```

Run the server from the source checkout:

```bash
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m title_mcp.mcp.server
```

Run it in Docker with MCP Inspector beside it:

```bash
docker compose up --build
```

Open the server catalog at `http://localhost:8000/` or the Inspector at
`http://localhost:6274/`, which is set up for Streamable HTTP at
`http://titlemcp:8000/mcp`. The Inspector asks for a session token, which
`docker compose logs mcp-inspector` prints. If it answers
`Forbidden - invalid origin`, open it through `http://localhost:6274/` or add your
browser's origin to `MCP_INSPECTOR_ALLOWED_ORIGINS`.

The Inspector's Resources tab has `titlemcp://server/info`,
`titlemcp://server/runtime`, `titlemcp://tools/catalog` and
`titlemcp://workflows/kinds`. Its Prompts tab has starter prompts for workflow
intake, parcel lookup review and HOA contact review.

Build the core package:

```bash
cd packages/titlemcp
../../.venv/bin/python -m build
../../.venv/bin/python -m twine check dist/*
```

## Jurisdiction packages

First-party jurisdiction packages live under `packages/jurisdictions`. Each package should have:

- `pyproject.toml`
- `src/<import_package>/`
- `tests/`
- `titlemcp-capability.toml`
- adapters, source connectors, vendor connectors, and manifests as needed

Use the package path as the release unit. For example, Franklin County recorder support publishes
from:

```text
packages/jurisdictions/us/oh/franklin/recorder
```

Audit a jurisdiction package before publishing:

```bash
.venv/bin/python scripts/audit_jurisdiction_package.py \
  packages/jurisdictions/us/oh/franklin/recorder
```

The publish workflow runs this audit automatically. If `publish=true`, the audit also requires
`release.publish = true`, every readiness flag to be true, and each workflow status to be `ready`.

## Generated jurisdiction catalog

`jurisdiction-catalog/` is generated reference scaffolding for country, state, county,
municipality, and county-subdivision organization. It is not package code and is not included in
the core wheel.

Regenerate it from the core package:

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean
```

## Contributing

Contributions are welcome — new jurisdiction packages, source and vendor
connectors, documentation, and fixes. A few conventions keep the project
consistent.

**Read [AGENTS.md](AGENTS.md) first.** It is the source of truth for the repo's
Pydantic v2 conventions, the tool/connector/test/sample contract for new
endpoints, the review-first rule, and the definition of done. Match the existing
patterns rather than introducing new ones.

### Workflow

The project uses the standard GitHub fork-and-pull-request flow:

1. **Fork** the repository and clone your fork.
2. **Branch** off `main` (e.g. `feat/...`, `fix/...`, `docs/...`).
3. **Make your change**, keeping each pull request focused on one thing.
4. **Add tests and a runnable sample** for any new tool or connector — code-only
   changes are not considered complete without them (see AGENTS.md §5–6).
5. **Run lint and the test suite** locally (below) and confirm they pass.
6. **Open a pull request** against `main` with a clear description of what
   changed and why.

Contributors without write access should fork; maintainers can push a branch
directly.

### Before you open a pull request

```bash
# Lint (Ruff: line length 100, target py312, rules E,F,I,UP,B)
.venv/bin/ruff check .
.venv/bin/ruff format --check .

# Core test suite
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover \
  -s packages/titlemcp/tests -v
```

For jurisdiction packages, also run that package's own test suite and the audit
script described in the [Jurisdiction packages](#jurisdiction-packages) section
above.

### What reviewers look for

- Everything at a boundary is a Pydantic v2 model — never a loose `dict`.
- Connectors return `REQUIRES_CONFIGURATION` or `FAILED` instead of raising, and
  default `requires_human_review=True` for title-impacting facts.
- Tools surface facts; they never make legal, underwriting, or recording
  decisions. The project stays **review-first**.
- Secrets are never logged, and sensitive identifiers are redacted.

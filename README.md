# Title MCP Monorepo

TitleMCP is a toolkit for title companies that want to expand their MCP server
tool surface with practical title and real estate operations capabilities. It is
designed to expose reusable, structured tools for local LLMs, hosted agents, and
workflow systems: parcel lookups, county auditor searches, PACER bankruptcy
checks, HOA contact discovery, public-records requests, tax certificates, HOA
estoppels, release tracking, payoff parsing, and other title workflows.

The project is intentionally tool-first. Each MCP tool should return predictable
domain records, preserve source-specific evidence, and leave legal or
underwriting judgment to a human reviewer. The goal is not to replace title
professionals; it is to give title companies a clean MCP server foundation they
can extend with jurisdiction-specific sources, vendor integrations, and internal
workflow automation.

This repository is organized as a Python package monorepo for TitleMCP.

> **Working with an AI agent or contributing code?** Read [AGENTS.md](AGENTS.md)
> first. It is the source of truth for Pydantic conventions, the tool/test/sample
> contract for new endpoints, and the review-first rule. (`CLAUDE.md` and
> `.github/copilot-instructions.md` point here too.)

## Start Here

New to the project? Start with the beginner docs:

- [Docs overview](docs/README.md)
- [Getting started](docs/GETTING_STARTED.md)
- [Tool reference](docs/TOOLS.md)
- [Configuration](docs/CONFIGURATION.md)
- [Samples](docs/SAMPLES.md)
- [Extending TitleMCP](docs/EXTENDING.md)
- [Agent & contributor guide](AGENTS.md)

```text
packages/
  titlemcp/                         # core framework published as titlemcp
  jurisdictions/
    us/
      oh/
        franklin/
          recorder/                 # titlemcp-us-oh-franklin-recorder
jurisdiction-catalog/               # generated geography/reference placeholders
```

The root is intentionally orchestration-only. Publishable Python packages live under `packages/`.

## Core Package

The reusable MCP framework is in `packages/titlemcp`.

```bash
.venv/bin/pip install -e "packages/titlemcp[dev]"
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover \
  -s packages/titlemcp/tests -v
```

Run the MCP server from the source checkout:

```bash
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m title_mcp.mcp.server
```

Run the Dockerized server and MCP Inspector:

```bash
docker compose up --build
```

Open the server catalog at `http://localhost:8000/` or the MCP Inspector at
`http://localhost:6274/`. The catalog response includes `mcp.url` and an
`inspector.url` with the backend prefilled for Docker. The Dockerized Inspector
also defaults to:

```text
Transport: Streamable HTTP
URL: http://titlemcp:8000/mcp
```

The Inspector proxy is bound to localhost by default. It requires a session token;
read the token from `docker compose logs mcp-inspector`. If you use the prefilled
URL printed by the container, replace `0.0.0.0` with `localhost` in your browser.
If the Inspector returns `Forbidden - invalid origin`, open it through
`http://localhost:6274/` or set `MCP_INSPECTOR_ALLOWED_ORIGINS` to include the
browser origin you are using.

The Inspector Resources tab includes `titlemcp://server/info`,
`titlemcp://server/runtime`, `titlemcp://tools/catalog`, and
`titlemcp://workflows/kinds`. The Prompts tab includes starter templates for
workflow intake, parcel lookup review, HOA contact review, and sample prompts
derived from the Ollama examples.

Build the core package:

```bash
cd packages/titlemcp
../../.venv/bin/python -m build
../../.venv/bin/python -m twine check dist/*
```

## Jurisdiction Packages

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

## Generated Jurisdiction Catalog

`jurisdiction-catalog/` is generated reference scaffolding for country, state, county,
municipality, and county-subdivision organization. It is not package code and is not included in
the core wheel.

Regenerate it from the core package:

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean
```

## Documentation

- Beginner docs: `docs/README.md`
- Core package README: `packages/titlemcp/README.md`
- Architecture: `packages/titlemcp/docs/ARCHITECTURE.md`
- Jurisdiction packages: `packages/titlemcp/docs/JURISDICTION_PACKAGES.md`
- Publishing: `packages/titlemcp/docs/PUBLISHING.md`

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

# Core test suite
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover \
  -s packages/titlemcp/tests -v
```

For jurisdiction packages, also run that package's own test suite and the audit
script described in the [Jurisdiction Packages](#jurisdiction-packages) section
above.

### What reviewers look for

- Everything at a boundary is a Pydantic v2 model — never a loose `dict`.
- Connectors return `REQUIRES_CONFIGURATION` or `FAILED` instead of raising, and
  default `requires_human_review=True` for title-impacting facts.
- Tools surface facts; they never make legal, underwriting, or recording
  decisions. The project stays **review-first**.
- Secrets are never logged, and sensitive identifiers are redacted.

# Razi Title MCP Monorepo

This repository is organized as a Python package monorepo for TitleMCP.

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

- Core package README: `packages/titlemcp/README.md`
- Architecture: `packages/titlemcp/docs/ARCHITECTURE.md`
- Jurisdiction packages: `packages/titlemcp/docs/JURISDICTION_PACKAGES.md`
- Publishing: `packages/titlemcp/docs/PUBLISHING.md`

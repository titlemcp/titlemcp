# Contributing

Contributions are welcome: new county packages, source and vendor connectors,
documentation, and fixes. A few conventions keep the project consistent.

**Read [AGENTS.md](AGENTS.md) first.** It is the source of truth for the repo's
Pydantic v2 conventions, the tool/connector/test/sample contract for new
endpoints, the review-first rule, and the definition of done. Match the existing
patterns rather than introducing new ones.

## Repository layout

```text
packages/
  titlemcp/                  # the core framework, published as titlemcp
  platforms/                 # scrapers shared by counties on the same software
    countyfusion/
    iasworld/
    publicsearch/
  jurisdictions/us/<state>/  # one package per county capability, e.g.
    tx/recorder/             #   titlemcp-us-tx-recorder
    va/tax/                  #   titlemcp-us-va-tax
samples/                     # runnable Ollama examples, one per lookup tool
docs/                        # user documentation
jurisdiction-catalog/        # generated geography scaffolding, not package code
```

The root is orchestration only. Every publishable Python package lives under
`packages/`.

## Workflow

The project uses the standard GitHub fork-and-pull-request flow:

1. **Fork** the repository and clone your fork.
2. **Branch** off `main` (e.g. `feat/...`, `fix/...`, `docs/...`).
3. **Make your change**, keeping each pull request focused on one thing.
4. **Add tests and a runnable sample** for any new tool or connector. Code-only
   changes are not considered complete without them (see AGENTS.md §5–6).
5. **Run lint and the test suite** locally (below) and confirm they pass.
6. **Open a pull request** against `main` with a clear description of what
   changed and why.

Contributors without write access should fork; maintainers can push a branch
directly.

## Before you open a pull request

```bash
# Every package, editable
./scripts/install.sh

# Lint (Ruff: line length 100, target py312, rules E,F,I,UP,B)
.venv/bin/pip install "ruff>=0.16,<0.17"
.venv/bin/ruff check .
.venv/bin/ruff format --check .

# Core test suite
.venv/bin/python -m unittest discover -s packages/titlemcp/tests -v

# One county or platform package's suite
.venv/bin/python -m unittest discover -s packages/jurisdictions/us/tx/recorder/tests -v
```

CI runs the core suite, every package's suite with all packages installed
together, and the publish audit below.

## County packages and the publish gate

Each county package needs `pyproject.toml`, `src/<import_package>/`, `tests/`,
`README.md` and `titlemcp-capability.toml`, plus the relevant `title_mcp.*`
entry points. Start from `packages/titlemcp/templates/jurisdiction-package/`;
[Jurisdiction packages](packages/titlemcp/docs/JURISDICTION_PACKAGES.md)
describes the contract.

The package directory is the release unit. Audit one before publishing:

```bash
.venv/bin/python scripts/audit_jurisdiction_package.py --require-publish-ready \
  packages/jurisdictions/us/tx/recorder
```

The publish workflow runs the same audit. Publishing requires
`release.publish = true`, every readiness flag true, and each workflow
`status = "ready"` with `human_review_required = true`.

## Building the core package

```bash
cd packages/titlemcp
../../.venv/bin/python -m build
../../.venv/bin/python -m twine check dist/*
```

Releases are cut by tagging; see AGENTS.md §10.

## Regenerating the jurisdiction catalog

`jurisdiction-catalog/` is generated reference scaffolding for country, state,
county, municipality and county-subdivision organization. It is not package
code and is not in the core wheel.

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean
```

## What reviewers look for

- Everything at a boundary is a Pydantic v2 model, never a loose `dict`.
- Connectors return `REQUIRES_CONFIGURATION` or `FAILED` instead of raising, and
  default `requires_human_review=True` for title-impacting facts.
- Tools surface facts; they never make legal, underwriting, or recording
  decisions. The project stays **review-first**.
- Secrets are never logged, and sensitive identifiers are redacted.

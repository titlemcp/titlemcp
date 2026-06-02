# AGENTS.md

Operating guide for AI agents (and humans) working in the TitleMCP monorepo.
**Read this before editing code.** It encodes the conventions this repo already
follows — match them; do not invent new patterns.

If you only remember three things:

1. **Everything at a boundary is a Pydantic v2 model** — never a loose `dict`.
2. **A new tool/connector is not done without unit tests _and_ a runnable sample.**
3. **Stay review-first** — surface facts, never make legal/underwriting/recording
   decisions. Default `requires_human_review=True` for title-impacting data.

Deeper references: [`docs/EXTENDING.md`](docs/EXTENDING.md),
[`packages/titlemcp/docs/ARCHITECTURE.md`](packages/titlemcp/docs/ARCHITECTURE.md).

---

## 1. What this project is

TitleMCP is a tool-first MCP server toolkit for title companies. Tools return
predictable, structured **domain records**, preserve source evidence, and leave
legal/underwriting judgment to a human reviewer. The MCP layer is intentionally
thin: tools validate input, call a service or connector, and serialize the
result. Durable state, jurisdiction routing, and legal decisions do **not** live
in the tool layer.

The repo is a Python package monorepo:

```text
packages/titlemcp/                 core framework (published as `titlemcp`)
packages/jurisdictions/us/oh/...   first-party jurisdiction packages
samples/                           runnable Ollama examples (one per tool)
jurisdiction-catalog/              generated reference data — NOT package code
```

---

## 2. Pydantic principles (non-negotiable)

This codebase is Pydantic v2 throughout. Follow the patterns in
`packages/titlemcp/src/title_mcp/domain/models.py`,
`sources/base.py`, and `sources/pacer.py`.

- **Every module starts with** `from __future__ import annotations`.
- **All inputs, outputs, queries, and records are `pydantic.BaseModel`** — never
  pass loose dicts across a boundary. Raw upstream payloads are the only `dict`
  allowed, and they go under a `source_specific` / `raw` field.
- **Use Pydantic v2 API only.** `model_validate(...)`, `model_dump(mode="json")`,
  `ConfigDict`, `field_validator`. Never `.dict()`, `.parse_obj()`, `@validator`,
  or `class Config` — those are v1 and must not appear.
- **Enums are `StrEnum`** (from `enum`), e.g. `SourceResultStatus`, `WorkflowKind`.
  Do not use bare string literals or `Enum` for closed value sets.
- **`model_config = ConfigDict(str_strip_whitespace=True)`** on any model holding
  user- or source-supplied strings.
- **Mutable defaults use `Field(default_factory=...)`** (`list`, `dict`, factory
  functions like `new_id`). Numeric bounds use `Field(default=..., ge=..., le=...)`
  — see `settings.py` for timeouts/ports.
- **Normalization happens in `@field_validator` + `@classmethod`** (e.g. upper-case
  country/state codes, strip names). Don't normalize ad hoc in callers.
- **Settings come from `TitleMCPSettings` (pydantic-settings), never `os.getenv`.**
  Env vars use the `TITLE_MCP_` prefix. Inject settings (`settings=...`) so they
  stay testable; resolve the singleton with `get_settings()`.
- **Canonical records carry schema metadata:** a stable `schema_name`
  (`title_mcp.<name>`), `schema_version`, `record_type`, a `source` block with
  retrieval info, and `source_specific` for the untouched upstream payload. See
  `PacerBankruptcySearchRecord`.
- **Modern typing only** (target is Python 3.12): `str | None`, `list[...]`,
  `dict[str, Any]`, `Annotated[...]`.

---

## 3. Where code belongs

Choose the narrowest extension point that fits. Don't put logic in the MCP layer.

| Location | Use for |
| --- | --- |
| `domain/` | Shared Pydantic records returned by tools/connectors. |
| `sources/` | Factual lookups: county recorders/auditors, courts, parcel/OCR/data APIs. |
| `vendors/` | Service-provider integrations: HOA estoppel, municipal lien, tax, payoff, release. |
| `adapters/` | Jurisdiction-aware workflow planning (what steps a jurisdiction needs). |
| `services/`, `workflows/` | Business state transitions and orchestration. |
| `mcp/tool_catalog.py` | **Core** MCP tools that every deployment should ship. |
| `mcp/toolsets.py` | Optional package toolsets that register extra MCP tools. |
| `capabilities/` | Install-time manifests describing what a package provides. |

Reusable jurisdiction behavior belongs in a **separate pip package** under
`packages/jurisdictions/...`, started from
`packages/titlemcp/templates/jurisdiction-package/`.

---

## 4. Adding a new MCP tool / endpoint

A new endpoint is a four-part contract: **tool + connector/service + tests +
sample.** All four ship together.

1. **Core vs. toolset.** Add to `mcp/tool_catalog.py` only if *every* deployment
   should have it. Otherwise ship a package toolset via the `title_mcp.toolsets`
   entry point.
2. **Register with the right annotation helper** so MCP clients get correct hints:
   - `_read_only_open_world(...)` — read-only lookups that hit external systems.
   - `_read_only_local(...)` — read-only over local/durable state.
   - `_state_changing(...)` — creates or mutates workflow state.
3. **Write a clear docstring** stating what the tool returns, including the
   canonical `schema_name`.
4. **Validate input into a typed Pydantic query model**, call the connector/service,
   and return `result.model_dump(mode="json")`. No business logic in the tool body.
5. **Connector behavior** (`sources/` / `vendors/`):
   - Return a `SourceResult` with a `SourceResultStatus`.
   - Missing credentials/config → return `REQUIRES_CONFIGURATION` with a helpful
     warning. **Do not raise.**
   - Caught failures → `FAILED` with a warning, not an unhandled exception.
   - Include `citations` with retrieval timestamps; default
     `requires_human_review=True` for title-impacting facts.
   - Wrap blocking network I/O behind an injectable client and run it via
     `asyncio.to_thread(...)` (see `PacerClient`).

---

## 5. Test requirements (mandatory)

Tests use the stdlib `unittest` framework (`unittest.IsolatedAsyncioTestCase` for
async). No new tool, connector, or domain change merges without tests. For each:

- **Input normalization** — criteria/query mapping behaves as intended.
- **Canonical mapping** — assert `schema_name`, `record_type`, and key fields of
  the returned record (see `test_pacer.py`).
- **Configuration-missing path** — asserts `REQUIRES_CONFIGURATION` when creds are
  absent.
- **Fakes, not live network** — use a fake client/session (e.g. `_FakePacerClient`).
  Keep live-network smoke tests out of the default suite.
- **Secret redaction** — assert SSNs/credentials are redacted in returned payloads.

For **jurisdiction packages** also test: the manifest matches
`titlemcp-capability.toml`, adapter routing for the jurisdiction, the source
connector contract, and add fixtures for representative responses (see
`packages/jurisdictions/us/oh/franklin/recorder/tests/test_contract.py`).

Run the core suite:

```bash
PYTHONPATH=packages/titlemcp/src .venv/bin/python -m unittest discover \
  -s packages/titlemcp/tests -v
```

Run a jurisdiction package suite (install both packages editable first):

```bash
python -m unittest discover \
  -s packages/jurisdictions/us/oh/franklin/recorder/tests -v
```

---

## 6. Sample requirements (mandatory)

Every new MCP tool gets a **runnable sample** proving a model selects it from a
natural prompt. Pattern: `samples/<name>_ollama/ollama_client.py` built on the
shared helper `samples._shared.ollama_mcp.run_tool_trigger_sample` (see
`samples/pacer_ollama/ollama_client.py`).

- The prompt **must not name the tool** — the sample verifies the model chooses it.
- The missing-credentials path must still trigger the tool and return
  `requires_configuration`.
- Add a `samples/<name>_ollama/README.md`, and link the sample from both
  `samples/README.md` and `docs/SAMPLES.md`.

---

## 7. Jurisdiction packages & the publish gate

Each publishable jurisdiction package needs: `pyproject.toml`, `src/<import_pkg>/`,
`tests/`, `README.md`, `titlemcp-capability.toml`, plus the relevant
`title_mcp.*` entry points. Naming: `titlemcp-us-oh-franklin-recorder` (dist) /
`titlemcp_us_oh_franklin_recorder` (import).

Audit before publishing — the publish workflow runs this automatically:

```bash
.venv/bin/python scripts/audit_jurisdiction_package.py \
  packages/jurisdictions/us/oh/franklin/recorder
```

Publishing additionally requires every `readiness` flag true, `release.publish =
true`, and each workflow `status = "ready"` with `human_review_required = true`.

---

## 8. Security & data handling

- **Never log** credentials, full SSNs, wire details, documents, or other
  sensitive payloads. Log source/workflow/jurisdiction IDs only.
- **Redact** sensitive identifiers in returned records and in any criteria you
  echo back (see `redacted_query` / `_redacted_ssn`).
- **Never hardcode secrets.** They come from `TITLE_MCP_*` settings.

---

## 9. Lint, format, and definition of done

Lint is Ruff (line length 100, target `py312`, rules `E,F,I,UP,B`):

```bash
.venv/bin/ruff check .
.venv/bin/ruff check --fix .   # autofix imports/lint where safe
```

**Definition of done for a new endpoint/connector:**

- [ ] Pydantic models for all I/O; v2 API only; `StrEnum` for enums.
- [ ] Tool registered with the correct annotation + schema-naming docstring.
- [ ] Connector returns `REQUIRES_CONFIGURATION` / `FAILED` instead of raising.
- [ ] `requires_human_review=True` for title-impacting facts.
- [ ] Unit tests: normalization, canonical mapping, missing-config, redaction.
- [ ] Runnable sample + sample README + links in `samples/README.md` and `docs/SAMPLES.md`.
- [ ] Secrets never logged; sensitive fields redacted.
- [ ] `ruff check` clean; relevant test suite green.

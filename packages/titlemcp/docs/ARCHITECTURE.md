# Architecture

TitleMCP is organized as a platform for title operations rather than a set of one-off MCP
functions. The core package owns the workflow state model, audit trail, and common MCP surface.
Jurisdiction and vendor behavior is installed around it through normal Python packages.

## Runtime Layers

```text
FastMCP transport
  -> core tool catalog and installed toolsets
    -> workflow services
      -> workflow engine
        -> workflow repository
        -> jurisdiction adapter registry
    -> source connector registry
    -> vendor connector registry
    -> capability registry
```

The MCP layer should stay thin. Tools validate input and call services. They should not directly
own durable state, county-specific routing rules, or legal decisions.

## Where New Capabilities Belong

Use these boundaries when adding functionality:

- `src/title_mcp/mcp/tool_catalog.py`: core MCP tools that should ship with every `titlemcp`
  installation.
- `src/title_mcp/mcp/toolsets.py`: entry point contract for optional packages that register
  additional MCP tools.
- `src/title_mcp/domain/`: portable Pydantic models shared by MCP tools, adapters, source
  connectors, vendor connectors, and future Django apps.
- `src/title_mcp/workflows/` and `src/title_mcp/services/`: workflow orchestration and service
  APIs. Business state transitions belong here.
- `src/title_mcp/adapters/`: jurisdiction-aware workflow planning. An adapter decides what steps
  are needed for a jurisdiction and workflow kind.
- `src/title_mcp/sources/`: public-record, county, court, tax, OCR, and other data source
  connectors. A source connector queries or normalizes facts but does not decide title issues.
- `src/title_mcp/vendors/`: service-provider integrations such as HOA estoppel, municipal lien,
  payoff, tax, release, title production, and underwriter systems.
- `src/title_mcp/capabilities/`: install-time manifests that describe what an extension package
  provides.
- `packages/titlemcp/templates/jurisdiction-package/`: starting point for pip-installable
  jurisdiction packages.

## Extension Points

Installed packages can expose these entry point groups:

```toml
[project.entry-points."title_mcp.adapters"]
my_adapter = "my_package.adapters:MyJurisdictionAdapter"

[project.entry-points."title_mcp.sources"]
my_source = "my_package.sources:MySourceConnector"

[project.entry-points."title_mcp.vendors"]
my_vendor = "my_package.vendors:MyVendorConnector"

[project.entry-points."title_mcp.capabilities"]
my_manifest = "my_package.manifest:capability_manifest"

[project.entry-points."title_mcp.toolsets"]
my_toolset = "my_package.toolsets:MyToolset"
```

The common path for county work is: manifest plus adapter plus source connector. Add a toolset only
when the package needs new MCP tools beyond the shared workflow tools.

## Title Industry Model

The domain layer includes workflow primitives and title-specific primitives:

- `WorkflowRecord`, `WorkflowTask`, `HumanReviewRequest`, and `AuditEvent` for durable operations.
- `Jurisdiction` for country, state, county, and municipality routing.
- `TitleMatterSnapshot`, `ParcelIdentifier`, `RecordingReference`, `LienReference`,
  `PayoffTerms`, `DocumentReference`, and `TitleParty` for title-order context.

These schemas are intentionally independent of FastMCP so they can later be embedded in Django
models, forms, admin views, Celery jobs, or external APIs.

## Review-First Rule

Adapters, source connectors, vendor connectors, OCR, and LLM-assisted extraction may produce
candidate facts, warnings, and next actions. They should default to `requires_human_review=True`
when facts affect title, settlement, legal, underwriting, payoff, lien, tax, or recording decisions.

The platform is designed to help title professionals work faster. It should not autonomously make
legal, curative, underwriting, disbursement, or recording decisions.

## Persistence And Observability

Workflow state is stored through `WorkflowRepository`. Local development uses the in-memory
repository; production deployments can use the Postgres repository. Records carry audit events,
timestamps, actor information, review status, and trace IDs.

Logging and trace helpers live under `src/title_mcp/observability/`. External connectors should log
source IDs, workflow IDs, vendor IDs, and jurisdiction keys, but must avoid logging credentials,
documents, full SSNs, wire details, or other sensitive payloads.

## Packaging Strategy

The core package is published as `titlemcp`. Jurisdiction packages should be published separately,
for example `titlemcp-us-oh-franklin-recorder`, and can be curated into extras such as:

```bash
python -m pip install "titlemcp[us-oh-franklin]"
```

Pip extras are declared by the core package release, so each bracket-style extra must be added to
`pyproject.toml` before publishing that `titlemcp` version. Jurisdiction packages can always be
installed directly from PyPI or a private package index.

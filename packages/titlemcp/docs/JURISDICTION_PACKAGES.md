# Jurisdiction Packages

The preferred way to distribute reusable jurisdiction behavior is a separate pip package that
depends on `titlemcp` and registers a capability manifest plus the adapters, source connectors, and
vendor connectors it provides.

That lets deployments install only the jurisdictions they need:

```bash
python -m pip install "titlemcp[us-oh-franklin]"
```

The `us-oh-franklin` extra is declared by the core `titlemcp` package and depends on the separate
`titlemcp-us-oh-franklin-recorder` jurisdiction package. That jurisdiction package must be
available on PyPI or on the private index configured for the deployment.

By default, `titlemcp-server` loads entry points from installed packages. Disable specific extension
types only for locked-down deployments:

```bash
TITLE_MCP_LOAD_ENTRY_POINT_ADAPTERS=false titlemcp-server
TITLE_MCP_LOAD_ENTRY_POINT_SOURCES=false titlemcp-server
TITLE_MCP_LOAD_ENTRY_POINT_VENDORS=false titlemcp-server
TITLE_MCP_LOAD_ENTRY_POINT_CAPABILITIES=false titlemcp-server
TITLE_MCP_LOAD_ENTRY_POINT_TOOLSETS=false titlemcp-server
```

## Naming Convention

Use package names that make scope obvious:

```text
titlemcp-us-oh-franklin-recorder
titlemcp-us-fl-miami-dade-public-records
titlemcp-us-md-baltimore-city-land-records
```

Use extras on `titlemcp` as curated install bundles:

```text
titlemcp[us-oh-franklin]
titlemcp[us-fl-miami-dade]
titlemcp[us-md-baltimore-city]
```

Important pip constraint: extras are not dynamically extensible by third-party packages. Every
`titlemcp[...]` extra must be listed in the core `titlemcp` release metadata. Jurisdiction packages
can always be installed directly, but the bracket syntax requires adding the extra to
`pyproject.toml` before releasing `titlemcp`.

Use Python import packages with underscores:

```text
titlemcp_us_oh_franklin_recorder
titlemcp_us_fl_miami_dade_public_records
```

## Minimal Package

```toml
[project]
name = "titlemcp-us-oh-franklin-recorder"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "titlemcp>=0.1.0",
    "websockets>=14.0,<16.0",
]

[project.entry-points."title_mcp.adapters"]
us_oh_franklin_recorder = "titlemcp_us_oh_franklin_recorder.adapters:FranklinCountyOhioRecorderAdapter"

[project.entry-points."title_mcp.sources"]
us_oh_franklin_recorder = "titlemcp_us_oh_franklin_recorder.sources:FranklinRecorderSourceConnector"

[project.entry-points."title_mcp.capabilities"]
us_oh_franklin_recorder = "titlemcp_us_oh_franklin_recorder.manifest:capability_manifest"
```

Each first-party jurisdiction package should also include `titlemcp-capability.toml` for readiness
tracking in CI. Keep `release.publish = false` until the package has fixtures, passing tests,
reviewed docs, and an explicit human approval.

Then add a core package extra:

```toml
[project.optional-dependencies]
"us-oh-franklin" = [
    "titlemcp-us-oh-franklin-recorder>=0.1.0",
]
```

The adapter is normal Python:

```python
from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import WorkflowKind


class FranklinCountyOhioRecorderAdapter:
    adapter_id = "us-oh-franklin-recorder-public-records"
    priority = 220
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})
    scope = JurisdictionScope(country="US", state="OH", county="Franklin County")

    def supports(self, jurisdiction):
        return self.scope.matches(jurisdiction)

    async def plan(self, request):
        ...
```

## Template

Start from:

```text
packages/titlemcp/templates/jurisdiction-package/
```

Copy it into `packages/jurisdictions/<country>/<state>/<county>/<capability>/`, rename the
package/import paths, implement the source client, and publish it to PyPI or a private package
index.

## Capability Boundaries

- Shared MCP tools stay in `titlemcp`.
- Jurisdiction packages supply capability manifests, adapters, source clients, schemas, and tests.
- JSON config is useful for simple routing and manual workflows.
- Python packages are better for source integrations, WebSocket protocols, auth, retries, parsing,
  and nontrivial normalization.
- Source connectors query government, public-record, OCR, and other factual sources.
- Vendor connectors place or track third-party service orders.
- Optional toolsets add new MCP-facing tools when the shared workflow tools are not enough.

Installed packages are loaded before workflow execution, then routed by jurisdiction, workflow kind,
source/vendor kind, and priority.

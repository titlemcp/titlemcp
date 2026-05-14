# Extending TitleMCP

TitleMCP has a small set of extension points. Choose the narrowest one that
matches the behavior you need.

## Where Code Belongs

- `domain/`: shared Pydantic records returned by tools and connectors.
- `sources/`: factual source lookups such as county auditors, parcel providers,
  courts, OCR providers, and public data APIs.
- `vendors/`: service-provider integrations such as HOA, municipal lien, tax,
  payoff, release, and title production vendors.
- `adapters/`: jurisdiction-aware workflow planning.
- `mcp/tool_catalog.py`: core MCP tools that should exist in every deployment.
- `mcp/toolsets.py`: optional package toolsets that add new MCP-facing tools.
- `capabilities/`: manifests that describe what a package provides.

## Add A Source Connector

Use a source connector when you query a system for facts and return normalized
records.

Examples in this codebase:

- Regrid parcel lookup returns `title_mcp.parcel_record`.
- PACER bankruptcy search returns `title_mcp.pacer_bankruptcy_search`.
- Franklin County Auditor returns `title_mcp.property_assessment_record`.

Rules of thumb:

- Return canonical domain records whenever possible.
- Preserve raw source data under `source_specific.<source_name>`.
- Include citations and retrieval timestamps.
- Redact credentials and sensitive identifiers in logs.
- Default `requires_human_review` to true for title-impacting facts.

## Add A Jurisdiction Adapter

Use an adapter when workflow planning changes by jurisdiction.

```python
from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind, WorkflowRequest


class MiamiDadePublicRecordsAdapter:
    adapter_id = "us-fl-miami-dade-public-records"
    priority = 150
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})
    scope = JurisdictionScope(country="US", state="FL", county="Miami-Dade")

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return self.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        ...
```

## Add A Jurisdiction Package

Reusable jurisdiction behavior should live in a separate pip package.

Package naming:

```text
titlemcp-us-oh-franklin-recorder
titlemcp-us-fl-miami-dade-public-records
```

Import package naming:

```text
titlemcp_us_oh_franklin_recorder
titlemcp_us_fl_miami_dade_public_records
```

Entry points:

```toml
[project.entry-points."title_mcp.adapters"]
my_adapter = "my_package.adapters:MyAdapter"

[project.entry-points."title_mcp.sources"]
my_source = "my_package.sources:MySourceConnector"

[project.entry-points."title_mcp.vendors"]
my_vendor = "my_package.vendors:MyVendorConnector"

[project.entry-points."title_mcp.capabilities"]
my_manifest = "my_package.manifest:capability_manifest"

[project.entry-points."title_mcp.toolsets"]
my_toolset = "my_package.toolsets:MyToolset"
```

Start from the template:

```text
packages/titlemcp/templates/jurisdiction-package/
```

## Add A New MCP Tool

Add a core tool only if every TitleMCP deployment should have it. Otherwise,
ship a package-specific toolset.

Core tools live in:

```text
packages/titlemcp/src/title_mcp/mcp/tool_catalog.py
```

Optional toolsets register through:

```text
title_mcp.toolsets
```

## Testing Expectations

For source connectors:

- Unit-test input normalization.
- Unit-test canonical mapping.
- Unit-test configuration-missing behavior.
- Use fake sessions/clients for network behavior.
- Keep live-network smoke tests out of default unit tests.

For jurisdiction packages:

- Test the manifest.
- Test adapter routing.
- Test source connector contracts.
- Add fixtures for representative source responses.

## Deeper Reference

- [Architecture](../packages/titlemcp/docs/ARCHITECTURE.md)
- [Jurisdiction Packages](../packages/titlemcp/docs/JURISDICTION_PACKAGES.md)
- [Publishing](../packages/titlemcp/docs/PUBLISHING.md)

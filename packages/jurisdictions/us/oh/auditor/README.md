# titlemcp-us-oh-auditor

Ohio county auditor **property-search** tools for TitleMCP. Covers the Ohio
counties whose auditor sites run the **Tyler iasWorld** platform; the scraping
and canonical-mapping logic is shared via
[`titlemcp-platform-iasworld`](../../../../platforms/iasworld/README.md).

Each covered county contributes:

- a `SourceConnector` (`us-oh-<county>-auditor`, kind `tax_authority`), and
- an MCP tool `<county>_auditor_search` returning canonical
  `title_mcp.property_assessment_record` records.

Counties are a **config table**, not code — see
`src/titlemcp_us_oh_auditor/sites.py` (`OH_IASWORLD_SITES`). Adding a county is a
new `IasWorldSiteConfig` entry plus a fixture-backed contract test and a sample.

## Covered counties

| County | Source id | Parcels | Status |
| --- | --- | --- | --- |
| Franklin | `us-oh-franklin-auditor` | numeric | enabled |
| Clermont | `us-oh-clermont-auditor` | alphanumeric | enabled |
| Montgomery | `us-oh-montgomery-auditor` | alphanumeric | enabled |

Confirmed on iasWorld and queued for enablement (need a captured fixture):
Stark, Butler, Lucas, Summit, Lake. See
[`docs/OHIO_AUDITOR_EXPANSION.md`](../../../../../docs/OHIO_AUDITOR_EXPANSION.md).

## How it registers

| Entry point | Class | Registers |
| --- | --- | --- |
| `title_mcp.plugins` | `OhioAuditorPlugin` | one source connector per county |
| `title_mcp.toolsets` | `OhioAuditorToolset` | one `<county>_auditor_search` tool per county |
| `title_mcp.adapters` | `OhioCountyAuditorAdapter` | OH `tax_certificate` workflow planning |
| `title_mcp.capabilities` | `capability_manifest` | install-time manifest |

The config-driven source connectors are registered via the `title_mcp.plugins`
hook because a `title_mcp.sources` entry point can only instantiate one no-arg
connector class.

## Tests

```bash
PYTHONPATH=packages/titlemcp/src:packages/platforms/iasworld/src:packages/jurisdictions/us/oh/auditor/src \
  .venv/bin/python -m unittest discover -s packages/jurisdictions/us/oh/auditor/tests -v
```

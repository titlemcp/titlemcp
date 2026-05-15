# Tool Reference

This page describes the MCP tools exposed by the current core server and the
first-party Franklin County package.

## Source Lookup Tools

### `hoa_contact_search`

Searches Google through SerpAPI for HOA contact information by association name
and optional state. The connector first looks for the likely official HOA
domain, then runs a second contact search restricted with `site:<domain>` when a
domain is found.

Input:

```json
{
  "hoa_name": "Example Woods HOA",
  "state": "Ohio"
}
```

Returns a canonical `title_mcp.hoa_contact_search` record with candidate HOA
contacts, websites, addresses, phone numbers, and email addresses when available
from the search result snippets or place panels. Raw candidate evidence is
preserved under each candidate and SerpAPI metadata is preserved under
`source_specific.serpapi`.

Configuration: `TITLE_MCP_SERPAPI_API_KEY`.

### `regrid_parcel_lookup`

Looks up parcel data by address using Regrid through the configured smart proxy.

Input:

```json
{
  "address": "1150 Glenn Ave, Columbus, OH"
}
```

Returns a canonical `title_mcp.parcel_record` with Regrid's original payload
preserved under `source_specific.regrid`.

Useful fields:

- `identifiers.parcel_number`
- `site.address`
- `ownership.owners`
- `land_use.use_code`
- `valuation.total_value`
- `building.year_built`
- `geography.geometry`

Configuration: `TITLE_MCP_SMART_PROXY` or legacy `SMART_PROXY`.

### `pacer_bankruptcy_search`

Searches PACER Case Locator bankruptcy party records for a person or business.

Person input:

```json
{
  "first_name": "John",
  "last_name": "Smith",
  "ssn4": "1234"
}
```

Business input:

```json
{
  "business_name": "Example Holdings LLC"
}
```

Returns `title_mcp.pacer_bankruptcy_search` records with redacted tax identifiers,
case rows, and a deterministic title-officer review flag.

Configuration:

- `TITLE_MCP_PACER_USERNAME`
- `TITLE_MCP_PACER_PASSWORD`
- `TITLE_MCP_PACER_CLIENT_CODE`
- `TITLE_MCP_PACER_QA_MODE`

Production PACER searches may be billable. Use QA credentials and
`TITLE_MCP_PACER_QA_MODE=true` for non-billable testing.

### `franklin_county_auditor_search`

Provided by the Franklin County Ohio jurisdiction package. Searches Franklin
County Auditor property records by parcel ID, owner, or address.

Parcel input:

```json
{
  "mode": "parid",
  "parcel_id": "030-000526-00",
  "include_details": true
}
```

Returns canonical `title_mcp.property_assessment_record` records with raw
Franklin Auditor detail preserved under `source_specific.franklin_auditor`.

## Workflow Tools

These tools create durable workflow records. They do not complete vendor work or
make legal decisions by themselves.

- `start_title_workflow`
- `analyze_document`
- `request_public_records_search`
- `request_hoa_estoppel`
- `request_municipal_lien_search`
- `request_tax_certificate`
- `track_release`
- `parse_payoff_letter`
- `generate_checklist_packet`

Common workflow arguments:

- `file_number`
- `state`
- `county`
- `municipality`
- `property_line1`
- `property_city`
- `property_postal_code`
- `requested_by`

Workflow responses include IDs, status, review state, audit events, and task
metadata.

## Status And Discovery Tools

- `get_workflow_status`
- `list_workflows`
- `submit_human_review`
- `list_title_capabilities`
- `list_source_connectors`
- `list_vendor_connectors`

These tools are useful for clients that need to inspect available capabilities
or resume existing work.

## Human Review Rule

TitleMCP tools default to `requires_human_review=true` when facts or workflows
can affect title, settlement, legal, underwriting, payoff, lien, tax, or
recording decisions.

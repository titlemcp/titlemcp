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

### `parcel_lookup`

Looks up parcel data by address.

Input:

```json
{
  "address": "100 Example Ave, Columbus, OH"
}
```

Returns a canonical `title_mcp.parcel_record`.

Useful fields:

- `identifiers.parcel_number`
- `site.address`
- `ownership.owners`
- `land_use.use_code`
- `valuation.total_value`
- `building.year_built`
- `geography.geometry`

Configuration: parcel provider credentials/proxy settings.

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

### `ofac_screen_parties`

Screens people and companies against OFAC's sanctions lists (the PATRIOT/OFAC
search a title file needs): the Specially Designated Nationals list and the
consolidated non-SDN lists, downloaded from Treasury's Sanctions List Service.

Input:

```json
{
  "parties": [
    {"name": "Jane Buyer", "party_type": "individual", "role": "buyer"},
    {"name": "Example Holdings LLC", "party_type": "entity", "role": "seller"}
  ],
  "changes_only": false
}
```

`party_type` is `individual`, `entity` or `unknown`; `date_of_birth` is optional and
is used to corroborate or discount a candidate (only its year is echoed back).

Returns a `title_mcp.ofac_screening` record: for each party an outcome
(`potential_match`, `likely_false_positive` or `no_match`) and its candidates, each
with the listed and matched names, the score and the reasons for it. Citations name
each list's publication date, entry count and file hash. Nothing is cleared
automatically: a potential match needs a person's review.

How matching keeps false alarms down without missing real matches:

- every listed name and alias is indexed by its words, their sounds-alike keys and
  character trigrams, with transliteration variants unified (MOHAMED and MUHAMMAD);
- words are aligned to words, tolerating reordering, initials, missing middle names
  and joined names;
- each word is weighted by how common it is in the United States (U.S. Census name
  frequencies), so "John Smith" partly matching a listed name stays quiet while a
  rare surname matching counts;
- an alias OFAC flags as weak cannot be a potential match by itself;
- a person never matches a vessel, aircraft or company, and generic company words
  ("Global", "Trading", "Holdings") weigh little; a company name made only of such
  words, or with one distinctive word that matches loosely, is not an alert;
- typos are expected: a swap of two letters costs one edit, and a mistyped
  transliteration (MOAHMED) or legal form (LIMITDE) is still recognised;
- matching only part of a longer listed name needs an exact, rare word;
- a date of birth that agrees corroborates; one that differs discounts.

Set `changes_only` to re-screen parties against only the entries added or changed
since the previous copy of the list: run it daily on open files.

### `ofac_list_status`

Which publication of each list screening uses: publish date, entry count, file
hash, when the copy was fetched, and how many entries changed since the previous
copy. `refresh=true` fetches the latest lists now.

Configuration: none required; see [Configuration](CONFIGURATION.md#ofac) for the
cache folder and refresh interval.

### `franklin_county_auditor_search`

Provided by the Ohio auditor jurisdiction package (`titlemcp-us-oh-auditor`),
built on the shared `titlemcp-platform-iasworld` scraper. Searches Franklin
County Auditor property records by parcel ID, owner, or address. Other Ohio
iasWorld counties expose the same tool as `<county>_auditor_search`.

Parcel input:

```json
{
  "mode": "parid",
  "parcel_id": "010-000123-00",
  "include_details": true
}
```

Returns canonical `title_mcp.property_assessment_record` records with the raw
auditor detail preserved under `source_specific.iasworld_auditor`.

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

## Inspector Resources

The server exposes read-only MCP resources for richer MCP Inspector debugging:

- `titlemcp://server/info`: server metadata, advertised capabilities, and counts.
- `titlemcp://server/runtime`: sanitized runtime configuration and integration status.
- `titlemcp://tools/catalog`: public tool catalog with schemas and annotations.
- `titlemcp://tools/{tool_name}`: detailed schema and annotations for one tool.
- `titlemcp://workflows/kinds`: workflow kinds accepted by workflow tools.

The HTTP server also exposes `GET /healthz` and `GET /readyz` for deployment
checks.

## Inspector Prompts

The server exposes prompt templates that can be tested in MCP Inspector:

- `title_workflow_intake`: prepare a structured title workflow request.
- `parcel_lookup_review`: review parcel lookup evidence for an address.
- `hoa_contact_review`: review HOA contact search evidence.
- `sample_parcel_lookup`: sample natural-language parcel lookup request.
- `sample_hoa_contact_search`: sample natural-language HOA contact request.
- `sample_bankruptcy_search`: sample natural-language bankruptcy search request.
- `sample_franklin_county_auditor_search`: sample Franklin County auditor request.

## Human Review Rule

TitleMCP tools default to `requires_human_review=true` when facts or workflows
can affect title, settlement, legal, underwriting, payoff, lien, tax, or
recording decisions.

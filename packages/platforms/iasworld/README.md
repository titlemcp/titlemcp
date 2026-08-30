# titlemcp-platform-iasworld

Shared scraper for county auditor / property-search sites running the **Tyler
Technologies "iasWorld"** web platform (the `search/commonsearch.aspx` +
`Datalets/Datalet.aspx` stack).

Many county auditor sites run the same iasWorld software; the search-form
submission and datalet parsing are identical across them. Only a few knobs
differ per county, captured by `IasWorldSiteConfig`:

| Knob | Example | Notes |
| --- | --- | --- |
| `base_url` | `https://property.franklincountyauditor.com/_web/` | Parent of `search/` and `Datalets/`. May be a bare domain (`https://www.mcrealestate.org/`). |
| `district_code` | `025` (Franklin), `000` (Clermont/Montgomery) | The iasWorld `jur` query parameter. |
| `mode_map` | `{ADDRESS: "realprop"}` | Override the `mode=` URL value (Summit/Lake serve a unified `realprop` search). |
| `numeric_parcel_ids` | `False` (Clermont) | Default `True` strips parcels to digits (Franklin `01000012300`); set `False` to preserve alphanumeric parcels (Clermont `100200C003D`, `100200.034C`). |

## What this package provides

- `IasWorldSiteConfig` — per-county configuration.
- `IasWorldAuditorClient` — the generic search + detail scraper.
- `IasWorldAuditorSearchQuery` / `…Hit` / `…ParcelDetail` / `…SearchResponse` — typed I/O models.
- `canonical_property_assessments_from_iasworld_response(...)` — maps a response
  to canonical `title_mcp.domain.auditor.PropertyAssessmentRecord` records.
- `build_auditor_source_connector(config)` — a `SourceConnector` for one county.
- `register_auditor_tool(mcp, platform, config)` (in `tooling`) — registers one
  `<county>_auditor_search` MCP tool.

## Usage

```python
from titlemcp_platform_iasworld import IasWorldSiteConfig, build_auditor_source_connector

config = IasWorldSiteConfig(
    source_id="us-oh-franklin-auditor",
    county="Franklin County",
    state="OH",
    name="Franklin County, Ohio Auditor Property Search",
    base_url="https://property.franklincountyauditor.com/_web/",
    district_code="025",
)
connector = build_auditor_source_connector(config)
```

Jurisdiction packages (e.g. `titlemcp-us-oh-auditor`) supply a table of these
configs and register one connector + MCP tool per county. This package is
state-agnostic — any iasWorld county, in any state, is just another config.

## When a detail page cannot be trusted

Two failures look identical to a healthy parse, because both come back as HTTP
200 and neither raises. The connector reports each as a warning on the result so
a caller is never handed empty fields as if they were the parcel's own.

| Situation | What the page is | What the connector does |
| --- | --- | --- |
| Site maintenance, bot block, error interstitial | Not a datalet: no data sections, no parcel number | Drops the detail and warns that no readable datalet was returned. The search hit is still reported. |
| Wrong `detail_profile` for the county | A real datalet whose tables the profile does not recognize | Keeps the record and warns which profile matched nothing, listing the sections the page actually served. |

`is_datalet_shaped(detail)` is the first check, and profile mismatches surface as
`detail.warnings`, merged into the search response. The mismatch check keys off
owner, mailing address and legal description all being empty on a page that does
have sections, since a datalet always names an owner somewhere.

## Tests

```bash
PYTHONPATH=packages/titlemcp/src:packages/platforms/iasworld/src \
  .venv/bin/python -m unittest discover -s packages/platforms/iasworld/tests -v
```

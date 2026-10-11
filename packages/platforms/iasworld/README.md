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
| `tax_page`, `tax_due_dates` | `CURRENT_YEAR_SUMMARY`, July 28 and December 5 (Fairfax) | Where the site shows tax, and when installments are due. See "Tax status". |

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

## Tax status

Each connector also answers `property_tax_status_search`, turning the county's
tax tables into a `title_mcp.property_tax_status` record. `tax_page` says where
the site shows tax and how it lays it out:

| `tax_page` | County | What it reads |
| --- | --- | --- |
| `AUDITOR` (default) | the Ohio auditors | The Annual Taxes table on the parcel's page: each year's net tax and total paid. Montgomery's page also has a Tax Summary by half. |
| `CURRENT_YEAR_SUMMARY` | Fairfax, VA | The `tax_details` tab: each half's charges, interest, penalty, payments and balance. |
| `BILLED_AND_PAYMENTS` | DuPage, IL | Taxes Billed (`tax_all`), each payment (`tax_collection`), and sold or forfeited taxes (`redemption`, `tax_status`). |
| `BALANCE_DUE` | Bernalillo, NM | The `tax_hist` tab: each year's tax, interest, penalty, fees, payments and amount due, and the current year's halves. |
| `COUNTY_RECEIVABLE` | Delaware, PA | The County Tax Receivable and Delinquent Tax tables on the parcel's page. |

Due dates come from `tax_due_dates` (a month and day, in the tax year or a year
after), moved past a weekend to the Monday, or from
`tax_due_months_after_billing` where the page gives each bill's date.
`tax_notes` adds what a reader should know about the county's page to every
answer.

- **Ohio auditors:** CDQ and Tax Lien flags become notes. The page shows no due
  dates, so a balance on the latest year is reported as owed, not past due.
- **Delinquent or sold taxes:** a table listing them marks those years and their
  amounts. One whose layout can't be read leaves every balance unknown, so the
  answer can't read paid while the county shows tax owed.
- **Data date:** the page's "Last Updated" or "Data last refreshed" date where it
  prints one, otherwise the day it was read.
- **The parcel asked about:** a numeric parcel search with no exact match falls
  back to wildcards, which can find a neighbouring parcel. A hit whose number
  isn't the one asked for is dropped, and the answer is `parcel_not_found`.
- **Disclaimers:** a site that sends a first visit to a click-through
  disclaimer (DuPage, Delaware PA) is agreed to once per session.

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

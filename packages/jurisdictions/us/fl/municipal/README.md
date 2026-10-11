# titlemcp-us-fl-municipal

Florida municipal lien directory for TitleMCP. Before a Florida closing, a title
agent orders a municipal lien search: what a city or county is owed on the
parcel that the official records don't show yet, such as code violations, open
permits, utility balances and special assessments. Each government answers in
its own way. This package records, for each one, who issues the lien letter and
how to order it, and where its permit, code case and utility records are.

It covers Florida's 67 counties and its 120 cities of 20,000 people or more. A
county's entry is for the county's own offices: the unincorporated area, and
what the county runs countywide. Jacksonville and Duval County are one
consolidated government.

## What it provides

- The source `us-fl-municipal-directory` (kind `municipal`) answers
  `municipal_lien_directory` with a `title_mcp.municipal_lien_directory` record:
  the city's entry and the county's.
- The adapter `us-fl-municipal-lien-search` plans `request_municipal_lien_search`
  workflows in Florida. Its first step names who issues the parcel's lien letter,
  how to order it, the fee and the turnaround. Further steps cover permits, code
  cases and utility balances the letter doesn't include, and special assessments.

## Each entry

| Field | What it records |
|---|---|
| `lien_letter` | Who issues it; how to order it (`online_portal`, `records_portal`, `email`, `form_email`, `mail`, `fax`, `phone`, `in_person`, `none_found`); the request page or address; the ordering vendor, where one takes the orders; the fee as published and per parcel; turnaround and rush; what it covers and excludes; the page that states it. |
| `permits` | The public permit search, its software (`accela`, `energov`, `centralsquare`, `citizenserve`, `mygovernmentonline`, `iworq`, `in_house`, `other`), what it searches by, and whether status shows without a login. |
| `code_enforcement` | Whether code cases can be searched publicly, and where. |
| `utilities` | Who provides water and sewer, solid waste and stormwater, the billing portal, and how a title agent asks for a balance. |
| `special_assessments` | Whether they are billed on the county tax bill, directly, or both, and who to ask. |
| `confidence` | `high` when read on the government's own pages; `medium` when read on a vendor's page, or on a copy of the government's page; `low` otherwise. |
| `checked_on` | The day the pages were read. |

## How it was gathered

Each government's own website was read for its lien search page, fee schedule
and request form, its permit and code case search, and its utility billing.
Software was identified from host names, paths, page titles and scripts. Only
landing, request, fee and search-form pages were read: no searches were run and
no requests were submitted.

`none_found` means no published process was found, not that the government
won't answer: many offices answer lien questions without publishing how. Fees
and processes change, so confirm on the government's page before ordering. The
answer says so when an entry is more than a year old.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/fl/municipal
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/fl/municipal/tests -v
```

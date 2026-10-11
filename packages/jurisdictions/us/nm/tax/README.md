# titlemcp-us-nm-tax

Bernalillo County, New Mexico property tax status for TitleMCP. It answers
`property_tax_status_search` by reading the Bernalillo County Treasurer's site live, through
[`titlemcp-platform-iasworld`](../../../../platforms/iasworld).

| County | Collector | Site |
| --- | --- | --- |
| Bernalillo County | Bernalillo County Treasurer | https://treasurer.bernco.gov/public.access/ |

## What it reads

The "Balance Due" tab: each year's tax, interest, penalty, fees, payments and amount due, and the current year's halves.

**Due dates:** November 10 and April 10 of the next year, as the county's page states, moved past a weekend to the Monday.

**Parcel number:** the county's 18-digit parcel number (UPC), dashes optional.

## Limits

- A due date moved by a holiday isn't known, so a balance can read past due a day early.

Every answer is marked for review. It is a reading of the county's record, not a
tax certificate.

## Install

```bash
pip install -e packages/platforms/iasworld -e packages/jurisdictions/us/nm/tax
```

It needs `titlemcp>=0.3.6` and `titlemcp-platform-iasworld>=0.3.0`. The county's
connector registers through the `title_mcp.plugins` entry point, which a server
loads only with `TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`.

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/nm/tax/tests -v
```

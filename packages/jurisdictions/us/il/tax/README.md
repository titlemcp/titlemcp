# titlemcp-us-il-tax

DuPage County, Illinois property tax status for TitleMCP. It answers
`property_tax_status_search` by reading the DuPage County Treasurer's site live, through
[`titlemcp-platform-iasworld`](../../../../platforms/iasworld).

| County | Collector | Site |
| --- | --- | --- |
| DuPage County | DuPage County Treasurer | https://propertylookup.dupagecounty.gov/ |

## What it reads

Taxes Billed on the "Tax Summary" tab, each payment on "Tax Payment History", and the "Tax Redemption" and "Tax Status" tabs for sold or forfeited taxes.

**Due dates:** June 1 and September 1 of the year after the tax year, moved past a weekend to the Monday.

**Parcel number:** the county's parcel number (PIN), such as 00-00-000-000 (dashes optional).

## Limits

- The page doesn't show installment amounts, so each is taken as half the bill, paid in order.
- The bill can set later due dates than June 1 and September 1, so a balance can read past due early.
- Sold or forfeited taxes whose table can't be read leave the balances unknown rather than paid.

Every answer is marked for review. It is a reading of the county's record, not a
tax certificate.

## Install

```bash
pip install -e packages/platforms/iasworld -e packages/jurisdictions/us/il/tax
```

It needs `titlemcp>=0.3.6` and `titlemcp-platform-iasworld>=0.3.0`. The county's
connector registers through the `title_mcp.plugins` entry point, which a server
loads only with `TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`.

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/il/tax/tests -v
```

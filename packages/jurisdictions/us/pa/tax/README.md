# titlemcp-us-pa-tax

Delaware County, Pennsylvania county real estate tax status for TitleMCP. It answers
`property_tax_status_search` by reading the Delaware County Treasurer's site live, through
[`titlemcp-platform-iasworld`](../../../../platforms/iasworld).

| County | Collector | Site |
| --- | --- | --- |
| Delaware County | Delaware County Treasurer | http://delcorealestate.co.delaware.pa.us/pt/ |

## What it reads

The County Tax Receivable table on the parcel's page: each bill's face amount, discount, penalty, payment and balance; and the Delinquent Tax table.

**Due dates:** Four months after each bill's billing date, the end of the face period (June 1 for a February 1 bill).

**Parcel number:** the county's folio number, such as 00-00-00000-00 (dashes optional).

## Limits

- County tax only: school district and municipal real estate taxes are billed by local collectors.
- A delinquent listing whose table can't be read leaves the balances unknown rather than paid.

Every answer is marked for review. It is a reading of the county's record, not a
tax certificate.

## Install

```bash
pip install -e packages/platforms/iasworld -e packages/jurisdictions/us/pa/tax
```

It needs `titlemcp>=0.3.6` and `titlemcp-platform-iasworld>=0.3.0`. The county's
connector registers through the `title_mcp.plugins` entry point, which a server
loads only with `TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`.

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/pa/tax/tests -v
```

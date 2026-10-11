# titlemcp-us-va-tax

Fairfax County, Virginia real estate tax status for TitleMCP. It answers
`property_tax_status_search` by reading the Fairfax County Department of Tax Administration's site live, through
[`titlemcp-platform-iasworld`](../../../../platforms/iasworld).

| County | Collector | Site |
| --- | --- | --- |
| Fairfax County | Fairfax County Department of Tax Administration | https://icare.fairfaxcounty.gov/ffxcare/ |

## What it reads

The "Tax Details" tab's Summary of Current Year Taxes: each half's tax, special district tax, interest, penalty, payments and balance.

**Due dates:** July 28 and December 5, as the county publishes them, moved past a weekend to the Monday.

**Parcel number:** the county's map number, such as 0000 00 0000 (spaces and dashes optional).

## Limits

- The page summarizes the current year only, so an unpaid earlier year isn't shown there.
- Herndon, Vienna and Clifton bill their own town real estate tax, which isn't on the county's site.
- A due date moved by a county holiday isn't known, so a balance can read past due a day early.

Every answer is marked for review. It is a reading of the county's record, not a
tax certificate.

## Install

```bash
pip install -e packages/platforms/iasworld -e packages/jurisdictions/us/va/tax
```

It needs `titlemcp>=0.3.6` and `titlemcp-platform-iasworld>=0.3.0`. The county's
connector registers through the `title_mcp.plugins` entry point, which a server
loads only with `TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`.

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/va/tax/tests -v
```

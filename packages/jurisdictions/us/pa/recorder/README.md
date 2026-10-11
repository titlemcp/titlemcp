# titlemcp-us-pa-recorder

Pennsylvania county recorder sources for TitleMCP. Each county contributes a
source connector (`us-pa-<county>-recorder`, kind `county_recorder`) that
searches the county's public index and answers `mortgage_release_search`.

Counties are a config table, not code: see
`src/titlemcp_us_pa_recorder/sites.py`. The protocol lives in
`titlemcp-platform-publicsearch`, and the release method in `title_mcp`.

## Covered counties

| County | Source id | Index |
| --- | --- | --- |
| Delaware | `us-pa-delaware-recorder` | `https://delaware.pa.publicsearch.us` |

In a sample of recent satisfactions, Delaware County's search results carried
no links to the mortgages, so the satisfaction is found from the text read off
its image, or picked out from the borrower's mortgages by the payoff date.
Checked by hand against recent satisfactions, they came back as candidates for a
reviewer: naming the borrower, but not tied to one mortgage.

## Release tracking

`PennsylvaniaReleaseTrackingAdapter` plans a `release_tracking` workflow for any
Pennsylvania county: check the county's index with `mortgage_release_search`,
follow up with the lender as the state's deadline runs out, and have a reviewer
confirm the release discharges the mortgage.

Pennsylvania's Mortgage Satisfaction Act gives the mortgagee 60 days from
receiving full payment and the borrower's first written request, sent by
certified or registered mail, to present a satisfaction for recording
(21 P.S. § 721-6).

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/jurisdictions/us/pa/recorder
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/pa/recorder/tests -v
```

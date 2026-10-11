# titlemcp-us-sc-recorder

South Carolina county recorder sources for TitleMCP. Each county contributes a
source connector (`us-sc-<county>-recorder`, kind `county_recorder`) that
searches the county's public index and answers `mortgage_release_search`.

Counties are a config table, not code: see
`src/titlemcp_us_sc_recorder/sites.py`. The protocol lives in
`titlemcp-platform-publicsearch`, and the release method in `title_mcp`.

## Covered counties

| County | Source id | Index |
| --- | --- | --- |
| Greenville | `us-sc-greenville-recorder` | `https://greenville.sc.publicsearch.us` |

In a sample of recent satisfactions, Greenville's search results carried no
links to the mortgages, so the satisfaction is found from the text read off its
image, or picked out from the borrower's mortgages by the payoff date.
Checked by hand against recent satisfactions, they came back as candidates for a
reviewer: naming the borrower, but not tied to one mortgage.
Greenville also records satisfactions by affidavit, which read as releases.

## Release tracking

`SouthCarolinaReleaseTrackingAdapter` plans a `release_tracking` workflow for any
South Carolina county: check the county's index with `mortgage_release_search`,
follow up with the lender as the state's deadline runs out, and have a reviewer
confirm the release discharges the mortgage.

South Carolina gives the holder three months from a request sent by certified
mail, or delivered with proof, to enter satisfaction (S.C. Code § 29-3-310).

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/jurisdictions/us/sc/recorder
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/sc/recorder/tests -v
```

# titlemcp-us-co-recorder

Colorado county recorder sources for TitleMCP. Each county contributes a
source connector (`us-co-<county>-recorder`, kind `county_recorder`) that
searches the county's public index and answers `mortgage_release_search`.

Counties are a config table, not code: see
`src/titlemcp_us_co_recorder/sites.py`. The protocol lives in
`titlemcp-platform-publicsearch`, and the release method in `title_mcp`.

## Covered counties

| County | Source id | Index |
| --- | --- | --- |
| Arapahoe | `us-co-arapahoe-recorder` | `https://arapahoe.co.publicsearch.us` |

Arapahoe's index links each release of a deed of trust to the deed of trust it
releases, so a lookup by the deed of trust's reception number is exact.

## Release tracking

`ColoradoReleaseTrackingAdapter` plans a `release_tracking` workflow for any
Colorado county: check the county's index with `mortgage_release_search`,
follow up with the lender as the state's deadline runs out, and have a reviewer
confirm the release discharges the mortgage.

Colorado gives the holder 90 days after the debt is paid to file the release
documents with the county's public trustee (C.R.S. 38-35-124), who records the
release of the deed of trust. The release's grantor is the public trustee, not
the lender.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/jurisdictions/us/co/recorder
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/co/recorder/tests -v
```

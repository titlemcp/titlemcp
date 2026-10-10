# titlemcp-us-oh-recorder

Ohio county recorder sources for TitleMCP. Each county contributes a source
connector (`us-oh-<county>-recorder`, kind `county_recorder`) that searches the
county's public index and answers `mortgage_release_search`.

Counties are a config table, not code: see
`src/titlemcp_us_oh_recorder/sites.py`. The protocol lives in the platform
package for each county's index, and the release method in `title_mcp`.

## Covered counties

| County | Source id | Platform |
| --- | --- | --- |
| Cuyahoga | `us-oh-cuyahoga-recorder` | Kofile PublicSearch |
| Stark | `us-oh-stark-recorder` | Kofile PublicSearch |
| Wayne | `us-oh-wayne-recorder` | Kofile CountyFusion |
| Ashland | `us-oh-ashland-recorder` | Kofile CountyFusion |

Wayne's own website doesn't link its index. Several CountyFusion hosts serve it;
the configured one is `countyfusion8.kofiletech.us`.

Franklin also runs PublicSearch and has its own package,
`titlemcp-us-oh-franklin-recorder`, which assembles a parcel's chain.

## Release tracking

`OhioReleaseTrackingAdapter` plans a `release_tracking` workflow for any Ohio
county: check the county's index with `mortgage_release_search`, follow up with
the lender if no release is recorded as the 90 days Ohio allows run out (R.C.
5301.36(B)), and have a reviewer confirm the release discharges the mortgage.

Releases are linked to their mortgages in all four counties' indexes, in both
directions, so a lookup by the mortgage's instrument number is exact. Without the number,
the borrower's name and the payoff date pick the mortgage out: the one open on
the payoff date and released since. Checked against live releases in both
counties, the releases found were recorded between a few days and two months
after the payoff, a median of about two weeks.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/platforms/countyfusion
python -m pip install -e packages/jurisdictions/us/oh/recorder
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/oh/recorder/tests -v
```

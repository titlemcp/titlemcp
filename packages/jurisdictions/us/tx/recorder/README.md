# titlemcp-us-tx-recorder

Texas county recorder sources for TitleMCP. Each county contributes a
source connector (`us-tx-<county>-recorder`, kind `county_recorder`) that
searches the county's public index and answers `mortgage_release_search`.

Counties are a config table, not code: see
`src/titlemcp_us_tx_recorder/sites.py`. The protocol lives in
`titlemcp-platform-publicsearch`, and the release method in `title_mcp`.

## Covered counties

| County | Source id | Index |
| --- | --- | --- |
| Dallas | `us-tx-dallas-recorder` | `https://dallas.tx.publicsearch.us` |
| Tarrant | `us-tx-tarrant-recorder` | `https://tarrant.tx.publicsearch.us` |
| Bexar | `us-tx-bexar-recorder` | `https://bexar.tx.publicsearch.us` |
| Collin | `us-tx-collin-recorder` | `https://collin.tx.publicsearch.us` |
| Denton | `us-tx-denton-recorder` | `https://denton.tx.publicsearch.us` |
| Hidalgo | `us-tx-hidalgo-recorder` | `https://hidalgo.tx.publicsearch.us` |
| Montgomery | `us-tx-montgomery-recorder` | `https://montgomery.tx.publicsearch.us` |

Bexar's index links each release to the deed of trust it releases. In a sample
of recent releases, the other six counties' search results carried no links, so
there the release is found from the text read off its image, or picked out from
the borrower's deeds of trust by the payoff date.

Checked by hand against recent releases: Bexar's were found by their links;
Dallas's, Collin's, Hidalgo's and Montgomery's mostly by their text citing the
deed of trust; and Tarrant's and Denton's came back as candidates for a reviewer,
naming the borrower but not tied to one deed of trust.

## Release tracking

`TexasReleaseTrackingAdapter` plans a `release_tracking` workflow for any
Texas county: check the county's index with `mortgage_release_search`,
follow up with the lender as the state's deadline runs out, and have a reviewer
confirm the release discharges the mortgage.

Texas gives the lender or servicer of a home loan 60 days from receiving the
payoff to deliver the release of lien to the borrower or file it with the county
clerk, or 30 days after a written request made within 20 days of the payoff
(Tex. Fin. Code § 343.108). A release delivered to the borrower may never be
recorded, so the plan asks the lender where it went before treating it as missing.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/platforms/publicsearch
python -m pip install -e packages/jurisdictions/us/tx/recorder
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/tx/recorder/tests -v
```

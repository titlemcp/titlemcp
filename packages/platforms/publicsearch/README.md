# titlemcp-platform-publicsearch

Shared client for county recorders whose public index runs on **Kofile's
PublicSearch** platform, at `https://<county>.<state>.publicsearch.us`. The
protocol is the same in every county, so a county is a `PublicSearchSiteConfig`,
not code.

## What it provides

- `PublicSearchSiteConfig`: one county's address, source id and document-type
  corrections.
- `PublicSearchClient`: the site's websocket protocol, mapped into the core's
  `title_mcp.domain.recorder.RecordedInstrument`.
- `PublicSearchIndex`: the lookups the core release method needs.
- `build_recorder_source_connector(config)`: a source connector that searches
  the index and answers `find_release` for `mortgage_release_search`.

```python
from titlemcp_platform_publicsearch import PublicSearchSiteConfig, build_recorder_source_connector

config = PublicSearchSiteConfig(
    source_id="us-oh-stark-recorder",
    county="Stark County",
    state="OH",
    name="Stark County, Ohio Recorder",
    base_url="https://stark.oh.publicsearch.us",
)
connector = build_recorder_source_connector(config)
```

## The protocol

There is no documented API. The site talks to its own page over a websocket:

1. One GET of the landing page sets two httpOnly cookies, `authToken` and
   `authToken.sig`. That is the whole credential; nothing is configured or
   stored. The session is reused for five minutes.
2. The websocket handshake carries the cookies, and each message repeats the
   token. A search is `@kofile/FETCH_DOCUMENTS/v4`; its answer is
   `FETCH_DOCUMENTS_FULFILLED`, matched on `correlationId` because other traffic
   shares the socket.

Searches are spaced at least half a second apart (`min_interval_seconds`).

## Releases and their mortgages

Each document can carry `marginalReferences`: the instruments the county's
indexers linked it to, with their types. Where a county links them, a mortgage
lists the releases and assignments recorded against it, and a release lists the
mortgage it discharges. That makes `mortgage_release_search` exact: look the
mortgage up, follow its links, and a release among them is the answer. Where no
link exists, the site's search of the text read off each image finds releases
that cite the mortgage's number.

Counties differ. Cuyahoga, Stark, Bexar, Arapahoe and Lake (Illinois) link
releases to their mortgages. In samples of recent releases, Dallas, Tarrant,
Collin, Denton, Hidalgo, Montgomery (Texas), Delaware (Pennsylvania) and
Greenville returned no links, so there the text search, or the borrower's name
and the payoff date, does the work. Some counties link by the site's own document
id, a bare number that names no instrument; those links are not followed.

The text read off images and the signed image links are not passed on; a match
on text keeps only a short excerpt around the number that matched.

## The index is not searched by address

Recorders index by party name, instrument number and legal description. A name
search spans the whole county, so a common name returns other people's
documents; the release method narrows by the payoff date and the links rather
than by name alone.

## Counties known to run PublicSearch

| County | Address | Package |
| --- | --- | --- |
| Cuyahoga, OH | `https://cuyahoga.oh.publicsearch.us` | `titlemcp-us-oh-recorder` |
| Franklin, OH | `https://franklin.oh.publicsearch.us` | `titlemcp-us-oh-franklin-recorder` |
| Stark, OH | `https://stark.oh.publicsearch.us` | `titlemcp-us-oh-recorder` |
| Dallas, TX | `https://dallas.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Tarrant, TX | `https://tarrant.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Bexar, TX | `https://bexar.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Collin, TX | `https://collin.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Denton, TX | `https://denton.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Hidalgo, TX | `https://hidalgo.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Montgomery, TX | `https://montgomery.tx.publicsearch.us` | `titlemcp-us-tx-recorder` |
| Arapahoe, CO | `https://arapahoe.co.publicsearch.us` | `titlemcp-us-co-recorder` |
| Lake, IL | `https://lake.il.publicsearch.us` | `titlemcp-us-il-recorder` |
| Delaware, PA | `https://delaware.pa.publicsearch.us` | `titlemcp-us-pa-recorder` |
| Greenville, SC | `https://greenville.sc.publicsearch.us` | `titlemcp-us-sc-recorder` |

Each county writes its own document types (Cuyahoga's `RELS - RELEASE
SATISFACTION` is Stark's `MORTGAGE RELEASE`, and Arapahoe's `RELEASE OF DEED OF
TRUST`); the core classifier reads them all, and `document_type_kinds` corrects it
by type code where a county's wording misleads it, as Dallas's `RELEASE OF LIEN`
does.

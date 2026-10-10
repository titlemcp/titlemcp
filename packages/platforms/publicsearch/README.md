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

## Releases are linked to their mortgages

Each document carries `marginalReferences`: the instruments the county's
indexers linked it to, with their types. A mortgage lists the releases and
assignments recorded against it, and a release lists the mortgage it discharges.
That is what makes `mortgage_release_search` exact here: look the mortgage up,
follow its links, and a release among them is the answer. Where no link exists,
the site's search of the text read off each image finds releases that cite the
mortgage's number.

The text read off images and the signed image links are not passed on; a match
on text keeps only a short excerpt around the number that matched.

## The index is not searched by address

Recorders index by party name, instrument number and legal description. A name
search spans the whole county, so a common name returns other people's
documents; the release method narrows by the payoff date and the links rather
than by name alone.

## Counties known to run PublicSearch

| County | Address |
| --- | --- |
| Cuyahoga, OH | `https://cuyahoga.oh.publicsearch.us` |
| Franklin, OH | `https://franklin.oh.publicsearch.us` |
| Stark, OH | `https://stark.oh.publicsearch.us` |

Each county writes its own document types (Cuyahoga's `RELS - RELEASE
SATISFACTION` is Stark's `MORTGAGE RELEASE`); the core classifier reads both, and
`document_type_kinds` corrects it by type code where a county's wording misleads
it.

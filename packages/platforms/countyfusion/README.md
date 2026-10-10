# titlemcp-platform-countyfusion

Shared client for county recorders whose public index runs on **Kofile's
CountyFusion** platform (also branded GovOS). Hosts are shared: one host serves
several counties, and a county key such as `WayneOH` picks the county. A county is
a `CountyFusionSiteConfig`, not code.

## What it provides

- `CountyFusionSiteConfig`: one county's host, county key, source id and
  document-type corrections.
- `CountyFusionClient`: the public session and the site's own search, result and
  detail requests, mapped into the core's
  `title_mcp.domain.recorder.RecordedInstrument`.
- `CountyFusionIndex`: the lookups the core release method needs.
- `build_recorder_source_connector(config)`: a source connector that searches the
  index and answers `find_release` for `mortgage_release_search`.

```python
from titlemcp_platform_countyfusion import CountyFusionSiteConfig, build_recorder_source_connector

config = CountyFusionSiteConfig(
    source_id="us-oh-ashland-recorder",
    county="Ashland County",
    state="OH",
    name="Ashland County, Ohio Recorder",
    host="countyfusion10.kofiletech.us",
    county_key="AshlandOH",
)
connector = build_recorder_source_connector(config)
```

## The site

There is no documented API; this sends what the site's own pages send.

- **A session** is the public login anyone gets from "Login as Public": a GET of
  the login page for its form token, the login post, and the disclaimer. No
  account and nothing stored; the only cookie is `JSESSIONID`.
- **Search state lives on the server**, per session, so a session runs one search
  at a time. The client serializes its searches and logs in again once if a
  session has lapsed.
- **A search** is three requests: the post, a redirect that sets up the results,
  and the result list page. A search that finds nothing answers with a page
  saying so rather than a redirect.
- **A document's detail** is a JSON call, and it answers only once the session
  has run a search.

Requests are spaced at least 1.1 seconds apart (`min_interval_seconds`). The hosts
reset HTTP/2 connections, so the client uses HTTP/1.1.

## Releases are linked to their mortgages

The result list only flags that a document has marginal references. Its detail
lists them: a release names the mortgage it discharges, and a mortgage names each
release and assignment recorded against it, with the instrument number, type and
recorded date of each. So `with_links` reads a mortgage's detail once, and the
release it points to is known without another request.

## Names

Names are matched from their start, and people are indexed surname first. The
index searches a person's name surname first ("DOE JANE"), and as given if that
finds nothing; a business's name is searched as written.

## Counties known to run CountyFusion

| County | Host | County key |
| --- | --- | --- |
| Ashland, OH | `countyfusion10.kofiletech.us` | `AshlandOH` |
| Wayne, OH | `countyfusion8.kofiletech.us` | `WayneOH` |

Each county writes its own document types: Ashland's `RELEASE MORTGAGE` is
Wayne's `MORTGAGE RELEASE`, Ashland abbreviates (`PT REL MORTGAGE`), and Wayne's
plain `RELEASE` code is a lease release. The core classifier reads all of these;
`document_type_kinds` corrects it by description where a county's wording
misleads it.

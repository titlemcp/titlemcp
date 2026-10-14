# titlemcp-platform-fidlarava

Shared client for county recorders whose public index runs on **Fidlar's AVA**
platform. Each county has its own AvaWeb app, the page its visitors search from,
and the app names the web API behind it. A county is a `FidlarAvaSiteConfig`,
not code.

## What it provides

- `FidlarAvaSiteConfig`: one county's app address, source id, request spacing
  and document-type corrections.
- `FidlarAvaClient`: the anonymous session and the site's own search request,
  mapped into the core's `title_mcp.domain.recorder.RecordedInstrument`.
- `FidlarAvaIndex`: the lookups the core release method needs.
- `build_recorder_source_connector(config)`: a source connector that searches the
  index and answers `find_release` for `mortgage_release_search`.

```python
from titlemcp_platform_fidlarava import FidlarAvaSiteConfig, build_recorder_source_connector

config = FidlarAvaSiteConfig(
    source_id="us-oh-medina-recorder",
    county="Medina County",
    state="OH",
    name="Medina County, Ohio Recorder",
    app_url="https://recorder-search.medinacounty.gov/OHMedina/AvaWeb/",
)
connector = build_recorder_source_connector(config)
```

## The site

There is no documented API; this sends what the AvaWeb app sends.

- **The API's address** is the `webApiBase` in the app's `appConfig.json`.
- **A session** is the app's anonymous login: a post of `breeze/Settings`, then
  the password grant to `token` as `anonymous`, password `anonymous`, for a
  bearer token. No account and nothing stored. When the API stops accepting the
  token (HTTP 401, or `ResultAction` 1) the client logs in again, once.
- **A search** is one post to `breeze/Search` of a criteria object holding every
  criterion the app knows, empty unless searched: `DocumentName` for an
  instrument number, `Book` and `Page`, or `LastBusinessName` with `FirstName`
  for a person. Dates go as ISO dates.
- **Each document found** (`DocResults`) carries its type, recorded date and time,
  book and page, its parties (party type 1 and 2), its notes and its associated
  documents.

Requests are spaced at least 1.1 seconds apart by default
(`min_interval_seconds`); a county that asks crawlers for more gets more.

## Captchas

The app sends a `FidlarCaptchaSolution` header with each search, for a reCAPTCHA
token where the site wants one. Searches are answered without one, so the header
goes empty. When a site asks for a captcha (HTTP 412, or a message naming one),
the client raises `FidlarAvaCaptchaRequired` and the connector reports `failed`
with a warning saying so. Nothing here solves or works around a captcha; such a
county has to be searched by hand.

## Releases are linked to their mortgages

`AssociatedDocuments` on a mortgage lists each release and assignment recorded
against it, and on a release, the mortgage it discharges. An association gives
the other document's instrument number and nothing more, so `with_links` looks
each one up by number to learn its type. A mortgage with a release and an
assignment costs three searches: the mortgage and one for each link. Everything
looked up is remembered for the rest of the lookup, so nothing is searched
twice.

AVA has no search of the text on document images, so `citing` finds nothing,
and where a county doesn't link a release to its mortgage the lookup falls back
to the parties.

## Book and page

A book and page search may match more than the one page asked for, so only an
exact match counts, leading zeros aside. A book and page given with leading
zeros is searched as given, then without them.

## Names

A person is searched by surname (`LastBusinessName`) and first name, and in the
other order if that finds nothing, in case the name was given surname first. A
business is searched by its whole name.

## Counties known to run AVA

| County | App |
| --- | --- |
| Lake, OH | `https://rep2laredo.fidlar.com/OHLake/AvaWeb/` |
| Medina, OH | `https://recorder-search.medinacounty.gov/OHMedina/AvaWeb/` |
| Holmes, OH | `https://ohholmes.fidlar.com/OHHolmes/AvaWeb/` |
| Geauga, OH | `https://ava.fidlar.com/OHGeauga/AvaWeb/` |

Each county writes its own document types: Medina's mortgage is `M` and its
release `CANC`, Holmes writes `SAT MTG` and `REL MTG`, Geauga `MORTGAGE
RELEASE` and Lake `RELEASE/SATISFACTION`. The core classifier reads most of
these; `document_type_kinds` corrects it by type where a county's wording
misleads it.

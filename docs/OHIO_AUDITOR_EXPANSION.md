# Ohio County Auditor Expansion

Roadmap for expanding county-auditor property-search coverage across Ohio.
Living document — update the county tables and status as work lands.

## The core idea: it's a *platform*, not a county

The original Franklin County auditor scraper is not really "Franklin code." It
is a client for **Tyler Technologies' iasWorld** property platform — the
`search/commonsearch.aspx` + `Datalets/Datalet.aspx` stack, the `inpNumber` /
`inpStreet` / `inpParid` form fields, `tr.SearchResults` rows, `DataletHeader`
tables, and the `jur:parid:taxyr` parcel token.

**Many Ohio county auditors run this exact software.** So the scraper, the typed
models, and the canonical mapping are reusable as-is; only a few per-county knobs
differ. A new iasWorld county becomes a **config entry**, not a new scraper.

The canonical output (`title_mcp.domain.auditor.PropertyAssessmentRecord`) is
already county-agnostic, so every county — iasWorld or bespoke — emits the same
record shape and downstream stays uniform.

## Architecture

```text
packages/platforms/iasworld/            titlemcp-platform-iasworld   (shared)
  config.py     IasWorldSiteConfig + AuditorSearchMode + mode resolution
  models.py     typed query / hit / detail / response models
  client.py     IasWorldAuditorClient + HTML parsers (the generic scraper)
  canonical.py  iasWorld response -> PropertyAssessmentRecord
  factory.py    build_auditor_source_connector(config)
  tooling.py    register_auditor_tool(mcp, platform, config)

packages/jurisdictions/us/oh/auditor/   titlemcp-us-oh-auditor       (config table)
  sites.py      OH_IASWORLD_SITES = [FRANKLIN, ...]   <- the per-county table
  plugin.py     title_mcp.plugins  -> registers one source connector per county
  toolsets.py   title_mcp.toolsets -> registers one <county>_auditor_search tool
  adapters.py   title_mcp.adapters -> OH tax_certificate workflow planning
  manifest.py   title_mcp.capabilities
```

The config-driven source connectors register through the `title_mcp.plugins`
hook (which receives the registries and can register many connectors at once),
because a `title_mcp.sources` entry point can only instantiate one no-arg
connector class.

### `IasWorldSiteConfig` knobs

Everything that differs between iasWorld counties:

| Knob | Example | Notes |
| --- | --- | --- |
| `base_url` | `https://property.franklincountyauditor.com/_web/` | Parent of `search/` and `Datalets/`. May be a bare domain (`https://www.mcrealestate.org/`) or a path prefix (`.../lucascare/`). A trailing slash is added if missing. |
| `district_code` | `025` (Franklin), `000` (Clermont/Montgomery) | The iasWorld `jur` query parameter. |
| `mode_map` | `{ADDRESS: "realprop"}` | Overrides the `mode=` URL value; Summit and Lake serve a unified `realprop` search instead of `address`. Lake maps **all** modes to `realprop`. |
| `numeric_parcel_ids` | `False` (Clermont) | Default `True` compacts parcels to digits (Franklin `01000012300`); `False` preserves alphanumeric parcels (Clermont `100200C003D`, `100200.034C`). |
| `form_field_overrides` | `{inpNumber: inpNo, inpOwner: inpOwner1}` (Lake) | Renames the POST field names submitted to the search form. Empty (default) = classic iasWorld names. Lake's unified `realprop` form uses `inpNo`/`inpOwner1` where the classic form uses `inpNumber`/`inpOwner`. |

`source_id`, `county`, `state`, `name`, `owner`, and `priority` round out the
config. New knobs are added when the first county actually needs one rather than
speculatively — `numeric_parcel_ids` was added exactly this way when Clermont
turned out to use alphanumeric parcels, and `form_field_overrides` exactly this
way when Lake's `realprop` form turned out to rename two POST fields. The same
happened for datalet section-name quirks: Lake's detail layout is a third variant,
now carried by its own `LAKE` `DetailProfile` rather than a per-site knob.

## Phase 0 — platform recon (complete)

Fingerprinting of Ohio's largest counties. iasWorld counties reuse the shared
scraper; bespoke counties need their own connectors (but the same canonical
output).

### iasWorld (reuse shared scraper)

| County | Search base URL | District / notes |
| --- | --- | --- |
| Franklin | `property.franklincountyauditor.com/_web/` | `jur=025`, numeric parcels — **enabled** |
| Clermont | `clermontauditorrealestate.org/_web/` | `jur=000`, **alphanumeric** parcels — **enabled** |
| Montgomery | `www.mcrealestate.org/` | `jur=000`, no `/_web/` prefix, **alphanumeric** parcels, CLASSIC detail (all verified live) — **enabled** |
| Stark | `realestate.starkcountyohio.gov/` | `jur=000` |
| Butler | `propertysearch.bcohio.gov/` | `jur=000`, **alphanumeric** parcels, PUBLIC_ACCESS detail (all verified live) — **enabled** |
| Lucas | `icare.co.lucas.oh.us/lucascare/` | branded "AREIS"; path prefix; `jur=048` (verified live), numeric parcels, CLASSIC detail — **enabled** |
| Summit | `propertyaccess.summitoh.net/` | uses `mode=realprop` |
| Lake | `auditor.lakecountyohio.gov/` | `jur=000`, **alphanumeric** parcels, unified `mode=realprop` search with renamed form fields (`inpNo`/`inpOwner1`), LAKE detail (all verified live) — **enabled** |

### Bespoke (need their own connector — grouped by vendor)

| Vendor / platform | Counties | Note |
| --- | --- | --- |
| DEVNET **wEdge** | Hamilton | `wedge.hcauditor.org` |
| **MyPlace** (in-house SPA) | Cuyahoga | base64-encoded routes |
| **Manatron** (Tyler family, different product) | Delaware | `*.manatron.com` — not iasWorld |
| **PivotPoint** / Schneider | Mahoning | `*.pivotpoint.us` |
| Custom ASP.NET MVC | Lorain, Greene | shared `/Search/Name` routing — likely one scraper covers both |
| Custom ASP.NET MVC / Razor | Warren | `.cshtml` routes |

> Warren and Lorain returned HTTP 403 to automated fetches (bot protection);
> their verdicts rest on indexed URLs. Confirm in a browser before building.

## Roadmap

### Phase 1 — extract & migrate Franklin (complete)

- Stood up `titlemcp-platform-iasworld` by lifting the Franklin auditor scraper +
  canonical mapper out of the recorder package and parameterizing over
  `IasWorldSiteConfig`.
- Created `titlemcp-us-oh-auditor` with Franklin as config entry #1.
- Removed the auditor from `titlemcp-us-oh-franklin-recorder` (it now ships only
  the recorder). The Franklin auditor tool, source id (`us-oh-franklin-auditor`),
  and tool name (`franklin_county_auditor_search`) are unchanged.
- Behavior preserved: the Franklin fixtures pass against the extracted scraper.
- Note: the canonical `source_specific` key was renamed
  `franklin_auditor` -> `iasworld_auditor` (platform-generic).

### Phase 2 — roll out iasWorld counties

**Clermont is enabled** (alongside the extraction) as the first proof that a
second county is mostly a config entry. It also surfaced the first real platform
variation — alphanumeric parcel IDs — which was absorbed by one shared knob
(`numeric_parcel_ids`) that every future alphanumeric-parcel county now inherits
for free. That is the extraction's payoff in one PR.

**Montgomery is enabled** as the third county and the first bare-domain base_url
(`https://www.mcrealestate.org/`, no `/_web/` prefix) — another config-only entry.
It also reuses the alphanumeric-parcel knob (`numeric_parcel_ids=False`) for its
letter-prefixed Parcel IDs (example `A01 00000 0001`). `jur=000` and the
alphanumeric parcels were confirmed against the live site; the datalet detail
profile could not be inspected live (maintenance / bot protection) so it keeps
the safe `detail_profile=CLASSIC` default pending live confirmation.

**Lucas is enabled** as the first AREIS-branded, path-prefix base-URL county
(`.../lucascare/`), confirming the platform layer handles a non-`/_web/` base. All
knobs were re-verified against the live site (an owner search returned result rows
with a reachable datalet): the parcel token is **`jur=048`** — not the `000`
regional default — so `district_code="048"`; parcels are numeric (`0100000`), so
`numeric_parcel_ids` stays the default `True`; and the datalet detail is the
combined-Owner `CLASSIC` layout (labels `Owner`/`Prior Owner`, not the numbered
Public Access sections), so `detail_profile` stays `CLASSIC`.

**Lake is enabled** — the first `realprop` county and the first to
need a form-field change. Its page identifies as iasWorld but serves a single
unified `realprop` Basic Search for parcel/owner/address, and that form renames
two POST fields (`inpNumber`->`inpNo`, `inpOwner`->`inpOwner1`). Confirmed live:
`jur=000`, alphanumeric parcels (`00A0000000001`, token `000:00A0000000002:2026`),
and standard `tr.SearchResults` result rows the shared parser already handles. Two
config knobs make search work — `mode_map` (every mode -> `realprop`) and the new
`form_field_overrides` — so search and the header-derived canonical fields
(parcel, owner, site address, token) populate. Its datalet **detail** layout,
however, is a third variant (sections `Owner Name and Mailing Address`, `Legal
Description Information`, `Appraised (Market - 100%) Value`, `Taxes Due`) that
neither `CLASSIC` nor `PUBLIC_ACCESS` fully parses, so deep detail extraction
(legal/taxes/valuation) remains a follow-up: a `LAKE` `DetailProfile`. That profile
has now landed (`detail_profile=LAKE`). The `form_field_overrides`
change is minimal and backward-compatible (no overrides = classic names; Franklin
and Clermont are unaffected, with a focused platform test pinning both).

**Butler is enabled** as another config-only county on the shared iasWorld stack
(`propertysearch.bcohio.gov/`). Re-verified live once site maintenance lifted (an
owner search returned result rows with a reachable datalet): `jur=000`, parcels
are alphanumeric (e.g. `A0000001`) so `numeric_parcel_ids=False`, and the datalet
detail uses the Public Access split layout with numbered labels (`Owner 1`,
`Address 1`), so `detail_profile=PUBLIC_ACCESS` — not the `CLASSIC` default.

Remaining: Stark, Summit — roughly in that order. Each county is one PR:

1. Append an `IasWorldSiteConfig` to `OH_IASWORLD_SITES` in `sites.py`.
2. Capture a real search + detail HTML **fixture** for that site.
3. Add a fixture-backed contract test (search parse, detail parse, canonical
   mapping, missing/empty path).
4. Add a runnable Ollama sample (`samples/<county>_auditor_ollama/`) whose prompt
   does **not** name the tool, plus its README and links.
5. Update the county table here and in the package README.

> Clermont's connector was validated end-to-end against the live site (search,
> alphanumeric parcels, and the Public Access detail profile all populate the
> canonical record). Its committed test fixtures use **synthetic** owner/parcel
> data — no real property records are checked into this open-source repo.

Add per-site politeness (User-Agent already derives from `base_url`; add rate
limiting / backoff) once multiple live counties are in play.

### Phase 3 — bespoke connectors

Separate packages per vendor, all emitting `PropertyAssessmentRecord`. Order by
leverage: Hamilton (wEdge) and the shared Lorain+Greene MVC scraper cover the
most ground per unit of work; Cuyahoga (MyPlace) is the highest-value single
county but the most custom. Manatron (Delaware) could become its own shared
platform package if other Ohio counties run it.

## Per-county definition of done

Mirrors the four-part contract in [`AGENTS.md`](../AGENTS.md):

- [ ] `IasWorldSiteConfig` entry in `sites.py` (or a bespoke connector).
- [ ] Source connector returns canonical records; `requires_human_review=True`.
- [ ] Contract tests: input normalization, canonical mapping, missing/empty path.
- [ ] Representative HTML fixture committed.
- [ ] Runnable sample + README + links in `samples/README.md` and `docs/SAMPLES.md`.
- [ ] `ruff check` clean; package + core suites green.

## Risks / open questions

- **Fixtures are the real Phase 2 cost.** The scraping logic is free; each county
  needs a captured search + detail page. Without one, a county stays disabled.
- **`mode=realprop` counties** (Summit, Lake) need form-field handling beyond the
  URL `mode` override — confirmed for Lake, whose `realprop` form renames two POST
  fields, now absorbed by the `form_field_overrides` knob. Summit still needs the
  same verification when enabled; its field names may differ again.
- **A third datalet layout was real.** Lake needed its own `LAKE` `DetailProfile`
  (singular labels, `-` placeholders, prefixed value tables, and section ids with
  trailing anchor markup). Expect a fourth: profiles, not per-site knobs, are the
  right unit for datalet differences. Two Lake gaps are the site's own — it serves
  no `DataletHeader` (site address comes from the search hit) and its datalet tab
  has no transfer/sales section, so `most_recent_transfer` is empty.
- **One readiness gate, many counties.** `titlemcp-us-oh-auditor` publishes as one
  package; a flaky county can hold the whole release. Consider per-site readiness
  flags in the config if this bites.
- **Bot protection** (403s on Warren/Lorain) means live connectors may need
  session/header care; keep live-network tests out of the default suite.

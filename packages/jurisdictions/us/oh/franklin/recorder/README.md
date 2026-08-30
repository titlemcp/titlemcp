# titlemcp-us-oh-franklin-recorder

Franklin County, Ohio recorder and auditor package for TitleMCP.

The recorder source reads the county's public index and assembles the recorded chain for one
parcel. It needs no credential: the county's search runs on Kofile's PublicSearch platform, which
talks over a websocket, and a plain connection is accepted and then closed. The credential is a
pair of httpOnly cookies (`authToken`, `authToken.sig`) issued by a GET of the landing page, which
the handshake must carry and which the same `authToken` value repeats inside every message. So a
session is one HTTP GET followed by a websocket presenting what it returned. No browser, no
account, nothing to store.

### It does not search by address

The recorder indexes by **party name** and **legal description**, never by street address. That is
the most common wrong assumption about county records: searching `1150 GLENN` returns a 1946
sheriff's deed, because `1150` matched a volume number. The auditor is where an address becomes a
parcel and an owner, and those two are what this searches with, so the order is auditor first.

### Scoping to one parcel is the whole job

A name search returns that party's documents across the entire county. On the search this was
built against, one owner returned twenty-one documents spanning three unrelated properties, two of
them in subdivisions named `FRANK S WAGENHALS ET AL AMENDED SUBD` and `WAGENHALS ET AL AMENDED
SUBD`. Matching on the subdivision picks the wrong chain and names the wrong lender, confidently.

What makes the answer right is that the county writes the parcel number into the legal description
of every instrument. That is the join, and `chain.py` is built on it. Two more things the obvious
implementation gets wrong, both taken from real records and both covered by tests:

- **A deed is only an acquisition if the owner is the grantee.** The same owner had a deed recorded
  a fortnight after buying, where they were the grantor: a different property, sold.
- **The lender is not the first name on a mortgage.** MERS appears as nominee on most modern
  instruments and a payoff never comes from it, so nominees are reported separately from lenders.

`requires_human_review` is always true. The index does not link a release to the mortgage it
discharges, so "open" means *no release naming this lender appears in the searched index*. That is
a reading of an index, not a title opinion, and the `basis` field on every lien says so.

It also includes a Franklin County Auditor property-search source and MCP toolset. The auditor
client searches the public address, owner, and parcel ID modes and returns search hits plus
structured parcel-detail sections from the official property record page. The source connector maps
those Franklin-specific fields into canonical `title_mcp.property_assessment_record` records for
downstream tools, while retaining the raw Franklin payload under
`source_specific.franklin_auditor`.

## Install Locally

```bash
python -m pip install -e .
```

After installation, `titlemcp-server` will discover the adapter through the `title_mcp.adapters`
entry point group. It also discovers this package's source connectors, auditor toolset, and
capability manifest through `title_mcp.sources`, `title_mcp.toolsets`, and
`title_mcp.capabilities`.

Neither source requires credentials. Its MCP tool is
`franklin_county_auditor_search`, with `mode` set to `address`, `owner`, or `parid`.

## Readiness

This package carries `titlemcp-capability.toml` so CI can check whether the jurisdiction is ready
to publish. Publishing should stay disabled until live-source behavior, fixtures, docs, and human
review expectations have been verified.

## Tests

```bash
python -m unittest discover \
  -s packages/jurisdictions/us/oh/franklin/recorder/tests -v
```

The recorder fixture is a real county response, trimmed, keeping all three properties because they
are what the scoping tests exist to catch. The default suite makes no network calls.

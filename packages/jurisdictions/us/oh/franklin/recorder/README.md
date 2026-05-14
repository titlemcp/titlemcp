# titlemcp-us-oh-franklin-recorder

Franklin County, Ohio recorder and auditor package for TitleMCP.

This example is scoped to Franklin County, Ohio public records search using a recorder source that
requires a custom client, such as a WebSocket protocol.

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

Set the recorder WebSocket endpoint for real queries:

```bash
export TITLEMCP_US_OH_FRANKLIN_RECORDER_WS_URL="wss://example.invalid/recorder"
```

The auditor source does not require credentials. Its MCP tool is
`franklin_county_auditor_search`, with `mode` set to `address`, `owner`, or `parid`.

## Readiness

This package carries `titlemcp-capability.toml` so CI can check whether the jurisdiction is ready
to publish. Publishing should stay disabled until live-source behavior, fixtures, docs, and human
review expectations have been verified.

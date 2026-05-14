# titlemcp-us-oh-franklin-recorder

Template package for a jurisdiction-specific TitleMCP adapter.

This example is scoped to Franklin County, Ohio public records search using a recorder source that
requires a custom client, such as a WebSocket protocol.

## Install Locally

```bash
python -m pip install -e .
```

After installation, `titlemcp-server` will discover the adapter through the `title_mcp.adapters`
entry point group. It also discovers this package's source connector and capability manifest
through `title_mcp.sources` and `title_mcp.capabilities`.

Set the recorder WebSocket endpoint for real queries:

```bash
export TITLEMCP_US_OH_FRANKLIN_RECORDER_WS_URL="wss://example.invalid/recorder"
```

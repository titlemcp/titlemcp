# Configuration

TitleMCP uses `pydantic-settings` and reads environment variables with the
`TITLE_MCP_` prefix. When the server is started from the repository root, `.env`
is loaded automatically by the settings layer.

## Server

```env
TITLE_MCP_LOG_LEVEL=INFO
TITLE_MCP_LOG_JSON=false
TITLE_MCP_MCP_TRANSPORT=stdio
TITLE_MCP_MCP_HOST=127.0.0.1
TITLE_MCP_MCP_PORT=8000
```

Common transports:

- `stdio`: normal MCP client mode.
- `streamable-http`: HTTP deployment mode.
- `sse`: server-sent events mode.

## State Backend

Local development defaults to in-memory state:

```env
TITLE_MCP_STATE_BACKEND=memory
```

Postgres:

```env
TITLE_MCP_STATE_BACKEND=postgres
TITLE_MCP_POSTGRES_DSN=postgresql://title_mcp:title_mcp@localhost:5432/title_mcp
```

Install the Postgres extra:

```bash
.venv/bin/pip install -e "packages/titlemcp[postgres]"
```

## Regrid

Regrid parcel lookup requires smart proxy configuration.

```env
TITLE_MCP_SMART_PROXY=user:password@proxy.example.com
TITLE_MCP_REGRID_PROXY_PORT_START=10001
TITLE_MCP_REGRID_PROXY_PORT_END=10999
TITLE_MCP_REGRID_MAX_PROXY_ATTEMPTS=10
TITLE_MCP_REGRID_TIMEOUT_SECONDS=10
TITLE_MCP_REGRID_COOKIE_TIMEOUT_SECONDS=5
```

Notes:

- `SMART_PROXY` is also supported as a legacy variable.
- Set the smart proxy host/auth without a rotating port. TitleMCP appends ports
  from the configured range.
- The Regrid connector disables `requests` environment proxy discovery so
  `TITLE_MCP_SMART_PROXY` is not mistaken for a generic proxy variable.
- The connector logs each proxy attempt with credentials redacted.

## PACER

```env
TITLE_MCP_PACER_USERNAME=
TITLE_MCP_PACER_PASSWORD=
TITLE_MCP_PACER_CLIENT_CODE=
TITLE_MCP_PACER_QA_MODE=true
TITLE_MCP_PACER_TIMEOUT_SECONDS=30
```

Use QA credentials and `TITLE_MCP_PACER_QA_MODE=true` for non-billable testing.
Production PACER queries may be billable.

## Ollama

```env
TITLE_MCP_OLLAMA_MODEL=qwen3
```

The sample clients also accept `--model`, for example:

```bash
python samples/franklin_county_ollama/ollama_client.py --model qwen3:8b
```

## Extension Loading

Installed packages are discovered through Python entry points by default.

```env
TITLE_MCP_LOAD_ENTRY_POINT_CAPABILITIES=true
TITLE_MCP_LOAD_ENTRY_POINT_ADAPTERS=true
TITLE_MCP_LOAD_ENTRY_POINT_SOURCES=true
TITLE_MCP_LOAD_ENTRY_POINT_VENDORS=true
TITLE_MCP_LOAD_ENTRY_POINT_TOOLSETS=true
TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=false
```

Disable a group only for locked-down deployments or focused tests.

## AWS Textract

Document-analysis workflows can be configured to use AWS integrations.

```env
TITLE_MCP_AWS_REGION=us-east-1
TITLE_MCP_TEXTRACT_S3_BUCKET=
```

Install the AWS extra:

```bash
.venv/bin/pip install -e "packages/titlemcp[aws]"
```

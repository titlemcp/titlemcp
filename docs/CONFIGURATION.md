# Configuration

TitleMCP uses `pydantic-settings` and reads environment variables with the
`TITLE_MCP_` prefix. Every setting has a working default, so the server starts
with none set.

A value is taken from, in order:

1. the process environment;
2. a `.env` file in the directory the server is started from;
3. the default.

## Credentials

Most tools need no credentials: OFAC screening, release search and tracking,
property tax status, the municipal lien directory, the county auditor searches
and the workflow tools work out of the box. These are the only secrets TitleMCP
reads. Each one switches on one tool, and a tool whose credential is missing
answers `requires_configuration` with the variable to set.

| Variable | Switches on | Where it comes from |
| --- | --- | --- |
| `TITLE_MCP_PACER_USERNAME`, `TITLE_MCP_PACER_PASSWORD` | `pacer_bankruptcy_search` | A PACER account. Searches can be billed to it; see [PACER](#pacer). |
| `TITLE_MCP_SERPAPI_API_KEY` | `hoa_contact_search` | A SerpAPI account. |
| `TITLE_MCP_SMART_PROXY` | `parcel_lookup` | A rotating proxy service, as `user:password@host`. See [Parcel Provider](#parcel-provider). |
| `TITLE_MCP_ANTHROPIC_API_KEY` | Exam extraction, a library service with no MCP tool | An Anthropic API key. |
| `TITLE_MCP_POSTGRES_DSN` | Durable workflow state | Your Postgres database. See [State Backend](#state-backend). |

[`.env.example`](../.env.example) lists them. To see which are set on a running
server, read the `titlemcp://server/runtime` resource: `configured_integrations`
says yes or no for each one and never shows a value.

### Where to keep them

TitleMCP only reads its environment, so any of these works:

- **A secret manager.** Keep the credentials in a vault and start the server
  through the manager's CLI, which puts them in the server's environment and
  writes nothing to disk. For example, `op run` (1Password), `doppler run`,
  `infisical run` or `aws-vault exec`:

  ```bash
  doppler run -- titlemcp-server
  ```

  This suits a team: each person signs in to the vault, access is granted and
  revoked there, and no one passes `.env` files around.
- **A local `.env`.** Copy `.env.example` to `.env` in the repository root, fill
  in the lines you need and start the server from the root. `.env` is ignored by
  git and left out of Docker builds.
- **An MCP client's configuration.** A client that starts the server over stdio
  (Claude Desktop, Claude Code, Cursor) chooses the working directory, so a
  `.env` may not be found. Put the variables in the server's `env` block:

  ```json
  {
    "mcpServers": {
      "titlemcp": {
        "command": "titlemcp-server",
        "env": { "TITLE_MCP_SERPAPI_API_KEY": "<your key>" }
      }
    }
  }
  ```

  That file is plain text on your machine. To keep the key in a vault instead,
  make the command the manager's CLI, for example `"command": "doppler"` with
  `"args": ["run", "--", "titlemcp-server"]`.
- **A hosted deployment.** Use the platform's secret or environment settings.
  The server has no sign-in, so read [Deploying](DEPLOY.md#before-you-deploy)
  before adding credentials to one.

### How the code handles them

- Each credential setting is a `SecretStr`. Printing, logging or dumping the
  settings shows `**********` in its place.
- The value is read with `secret_value()` only at the call that sends it to
  the service.
- Logs name proxy endpoints with the user and password removed, and PACER
  criteria are logged without SSNs.
- Samples, fixtures and committed configuration hold no real credentials.
  Tests use invented values.

## Server

```env
TITLE_MCP_LOG_LEVEL=INFO
TITLE_MCP_LOG_JSON=false
TITLE_MCP_MCP_TRANSPORT=stdio
TITLE_MCP_MCP_HOST=127.0.0.1
TITLE_MCP_MCP_PORT=8000
TITLE_MCP_MCP_PUBLIC_URL=
TITLE_MCP_INSPECTOR_URL=
TITLE_MCP_INSPECTOR_BACKEND_URL=
TITLE_MCP_MCP_DNS_REBINDING_PROTECTION=true
TITLE_MCP_MCP_ALLOWED_HOSTS=
TITLE_MCP_MCP_ALLOWED_ORIGINS=
```

Common transports:

- `stdio`: normal MCP client mode.
- `streamable-http`: HTTP deployment mode.
- `sse`: server-sent events mode.

The Docker image runs `streamable-http` on `0.0.0.0:8000`. When a hosting
platform sets `PORT`, the image listens there instead of on
`TITLE_MCP_MCP_PORT`. See [Deploying](DEPLOY.md).

The HTTP discovery response at `/` advertises an absolute MCP endpoint as
`mcp.url`. By default it is derived from the request host. Set
`TITLE_MCP_MCP_PUBLIC_URL` when a proxy or deployment URL should be advertised
instead.

Set `TITLE_MCP_INSPECTOR_URL` to the browser URL for MCP Inspector and
`TITLE_MCP_INSPECTOR_BACKEND_URL` to the backend URL the Inspector proxy should
connect to. When both services run through `docker compose`, the backend URL is
`http://titlemcp:8000/mcp` because that is the service name visible from the
Inspector container. The compose service passes that URL to Inspector at startup
so direct visits to `http://localhost:6274/` default to Streamable HTTP instead
of Inspector's sample STDIO server.

HTTP deployments can opt into explicit DNS-rebinding protection allowlists:

```env
TITLE_MCP_MCP_ALLOWED_HOSTS=localhost:*,127.0.0.1:*,titlemcp:*
TITLE_MCP_MCP_ALLOWED_ORIGINS=http://localhost:*,http://127.0.0.1:*
```

`docker-compose.yml` sets these for local Inspector usage. If you expose the
Inspector on a different host or port, set `MCP_INSPECTOR_ALLOWED_ORIGINS` for
the Inspector proxy as well, for example
`MCP_INSPECTOR_ALLOWED_ORIGINS=http://localhost:6275`.

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

## Parcel Provider

Parcel lookup requires smart proxy configuration.

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
- The parcel connector disables `requests` environment proxy discovery so
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

## OFAC

OFAC screening needs no credentials: the lists are public. They are downloaded from
`sanctionslistservice.ofac.treas.gov` and cached.

```env
TITLE_MCP_OFAC_CACHE_DIR=~/.cache/titlemcp/ofac
TITLE_MCP_OFAC_MAX_AGE_HOURS=24
TITLE_MCP_OFAC_TIMEOUT_SECONDS=120
```

If a refresh fails, the cached copy is used and the result warns when it is more
than two days old. With no cached copy and no network, screening returns `failed`.

## SerpAPI

HOA contact lookup uses SerpAPI's Google Search API.

```env
TITLE_MCP_SERPAPI_API_KEY=
TITLE_MCP_SERPAPI_TIMEOUT_SECONDS=30
```

Keep the key where [Credentials](#where-to-keep-them) describes, never in sample
code or committed configuration.

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

Most county packages register as plugins, so they load only with
`TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`. The Docker image sets it.

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

# Deploying TitleMCP

Each button builds this repository's `Dockerfile` on the platform and runs the
server over Streamable HTTP. When the deployment is up, it serves:

| Path | What it is |
| --- | --- |
| `/mcp` | The MCP endpoint that clients connect to. |
| `/` | A JSON catalog of the tools, resources and prompts, with the endpoint's full URL. |
| `/healthz` | A health check. |

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/titlemcp/titlemcp)
[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy?template=https://github.com/titlemcp/titlemcp)
[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run?git_repo=https://github.com/titlemcp/titlemcp)
[![Deploy to DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/titlemcp/titlemcp/tree/main)
[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=git&repository=github.com/titlemcp/titlemcp&branch=main&builder=dockerfile&name=titlemcp&ports=8000;http;/&env%5BPORT%5D=8000)

## Before you deploy

- **The server has no sign-in.** Anyone who has the URL can list and call its
  tools. A tool that uses credentials you configure (PACER, SerpAPI, Anthropic,
  the parcel proxy) uses them for whoever calls it, and PACER and the paid APIs
  bill per use. Leave those unset on a public deployment, or deploy somewhere
  only your own clients can reach.
- **Every county package is in the image and loaded**; the image sets
  `TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true`. Their tools read the counties'
  public websites when they are called.
- **State is kept in memory.** Workflow records are lost when the service
  restarts or redeploys, and free instances restart often. For durable state,
  set `TITLE_MCP_STATE_BACKEND=postgres` and `TITLE_MCP_POSTGRES_DSN` (see
  [Configuration](CONFIGURATION.md#state-backend)).
- **Memory.** The server idles at about 60 MB. The first OFAC screening
  downloads and parses the sanctions lists and takes it to about 450 MB. A
  512 MB instance runs it; 1 GB leaves room.
- **Version.** An image built from the repository reports the latest release on
  PyPI plus `+source`, for example `0.3.6+source`.

## Platforms

| Platform | Configured by | Notes |
| --- | --- | --- |
| Render | [`render.yaml`](../render.yaml) | Uses the free plan. Free instances stop when idle, and the first request afterwards waits while one starts. Automatic deploys are off, so redeploy from the dashboard to pick up new commits. |
| Heroku | [`app.json`](../app.json), [`heroku.yml`](../heroku.yml) | Builds on the container stack. Heroku has no free plan. |
| Google Cloud Run | [`app.json`](../app.json) | Runs from Cloud Shell and needs a Google Cloud project with billing. The service accepts unauthenticated requests. Cloud Run's default is 512 MiB; for OFAC screening, raise it with `gcloud run services update titlemcp --memory 1Gi`. |
| DigitalOcean App Platform | [`.do/deploy.template.yaml`](../.do/deploy.template.yaml) | Health-checks `/healthz` on port 8000. |
| Koyeb | The button's link | Serves port 8000. |

Any other host that builds a Dockerfile can run it too, such as Railway, Fly.io,
Azure Container Apps or AWS App Runner. The container:

- listens on `PORT` when the platform sets it, and on 8000 otherwise;
- answers health checks at `GET /healthz`;
- trusts the proxy's `X-Forwarded-Proto`, so the catalog advertises `https://`
  URLs. Set `TITLE_MCP_MCP_PUBLIC_URL` to advertise a different address.

## Configure it

Add `TITLE_MCP_*` variables in the platform's environment settings. Every
setting is described in [Configuration](CONFIGURATION.md). The service picks
them up when it restarts.

## Connect a client

Check that the deployment answers:

```bash
curl https://<your-app>/healthz
```

Then point an MCP client at `https://<your-app>/mcp`:

- **Claude Code:** `claude mcp add --transport http titlemcp https://<your-app>/mcp`
- **Claude (web and desktop):** add a custom connector with the same URL.
- **MCP Inspector:** run `npx @modelcontextprotocol/inspector`, choose
  Streamable HTTP, and enter the URL.

## Build the image yourself

```bash
docker build -t titlemcp .
docker run -p 8000:8000 titlemcp
```

A release image is built with its version:

```bash
docker build --build-arg TITLEMCP_VERSION=0.3.6 -t titlemcp:0.3.6 .
```

For local work with MCP Inspector alongside, use `docker compose up --build` as
described in [Getting Started](GETTING_STARTED.md#run-it-in-docker).

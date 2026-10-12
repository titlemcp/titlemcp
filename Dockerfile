FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TITLE_MCP_ENVIRONMENT=docker \
    TITLE_MCP_LOG_JSON=true \
    TITLE_MCP_MCP_TRANSPORT=streamable-http \
    TITLE_MCP_MCP_HOST=0.0.0.0 \
    TITLE_MCP_MCP_PORT=8000

# A hosting platform ends TLS at its own proxy and passes the original scheme on
# in X-Forwarded-Proto. Trusting it lets the catalog at / advertise https URLs.
ENV FORWARDED_ALLOW_IPS=*

# The package takes its version from the release tag, and a build context has no
# .git to read it from. A release image is built with its number:
#   docker build --build-arg TITLEMCP_VERSION=0.3.6 .
# Without one, the image is the latest release on PyPI plus this source tree,
# for example 0.3.6+source, which still satisfies jurisdiction packages that
# require a minimum core version.
ARG TITLEMCP_VERSION=

WORKDIR /app

# A system user's home is /nonexistent unless one is given. Caches such as the
# OFAC sanctions lists are kept under ~/.cache, so the user needs a real one.
RUN addgroup --system titlemcp \
    && adduser --system --ingroup titlemcp --home /home/titlemcp titlemcp

COPY packages/titlemcp/pyproject.toml \
     packages/titlemcp/README.md \
     packages/titlemcp/LICENSE \
     packages/titlemcp/
COPY packages/titlemcp/src packages/titlemcp/src

COPY packages/jurisdictions/us/oh/franklin/recorder/pyproject.toml \
     packages/jurisdictions/us/oh/franklin/recorder/README.md \
     packages/jurisdictions/us/oh/franklin/recorder/titlemcp-capability.toml \
     packages/jurisdictions/us/oh/franklin/recorder/
COPY packages/jurisdictions/us/oh/franklin/recorder/src \
     packages/jurisdictions/us/oh/franklin/recorder/src

RUN python -m pip install --upgrade pip \
    && released=$(python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/titlemcp/json', timeout=30))['info']['version'])") \
    && SETUPTOOLS_SCM_PRETEND_VERSION="${TITLEMCP_VERSION:-$released+source}" python -m pip install \
        "packages/titlemcp[postgres]" \
        "packages/jurisdictions/us/oh/franklin/recorder"

USER titlemcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, socket; s = socket.create_connection(('127.0.0.1', int(os.getenv('PORT') or os.getenv('TITLE_MCP_MCP_PORT', '8000'))), timeout=3); s.close()"

# Hosting platforms (Render, Heroku, Cloud Run, Railway and others) choose the
# port and pass it as PORT. When it is set, the server listens there.
CMD ["sh", "-c", "TITLE_MCP_MCP_PORT=\"${PORT:-$TITLE_MCP_MCP_PORT}\" exec titlemcp-server"]

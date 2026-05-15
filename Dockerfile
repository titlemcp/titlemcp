FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TITLE_MCP_ENVIRONMENT=docker \
    TITLE_MCP_LOG_JSON=true \
    TITLE_MCP_MCP_TRANSPORT=streamable-http \
    TITLE_MCP_MCP_HOST=0.0.0.0 \
    TITLE_MCP_MCP_PORT=8000

WORKDIR /app

RUN addgroup --system titlemcp \
    && adduser --system --ingroup titlemcp titlemcp

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
    && python -m pip install \
        "packages/titlemcp[postgres]" \
        "packages/jurisdictions/us/oh/franklin/recorder"

USER titlemcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, socket; s = socket.create_connection(('127.0.0.1', int(os.getenv('TITLE_MCP_MCP_PORT', '8000'))), timeout=3); s.close()"

CMD ["titlemcp-server"]

#!/bin/sh
# Install TitleMCP and every county package into .venv, then print how to
# connect an MCP client to it.
#
#   ./scripts/install.sh
#   PYTHON=python3.13 ./scripts/install.sh
#
# Run it from a git clone. The core package takes its version from the
# repository's tags, and the county packages require a minimum core version.
set -eu

cd "$(dirname "$0")/.."
python=${PYTHON:-python3}

if ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    echo "TitleMCP needs Python 3.12 or newer, and $python is not." >&2
    echo "Run it with a newer one, for example: PYTHON=python3.12 $0" >&2
    exit 1
fi
if ! git describe --tags --abbrev=0 >/dev/null 2>&1; then
    echo "This copy has no release tags, so the package version can't be read." >&2
    echo "Use a full clone: git clone https://github.com/titlemcp/titlemcp" >&2
    echo "(In a shallow clone, 'git fetch --tags' adds them.)" >&2
    exit 1
fi

"$python" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
# shellcheck disable=SC2046 # one argument per package directory
.venv/bin/python -m pip install --quiet -e packages/titlemcp \
    $(find packages/platforms packages/jurisdictions -name pyproject.toml -exec dirname {} \; \
        | sort | sed 's/^/-e /')

server="$(pwd)/.venv/bin/titlemcp-server"
cat <<EOF

TitleMCP is installed, with every county package.

Claude Code:
  claude mcp add titlemcp -e TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true -- $server

Claude Desktop (Settings > Developer > Edit Config), inside "mcpServers":
  "titlemcp": {
    "command": "$server",
    "env": {"TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS": "true"}
  }

Any other MCP client: run $server over stdio,
with TITLE_MCP_LOAD_ENTRY_POINT_PLUGINS=true in its environment.
EOF

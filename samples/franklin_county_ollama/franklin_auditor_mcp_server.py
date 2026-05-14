from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path

LOGGER = logging.getLogger("samples.franklin_county_ollama.server")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def local_src_paths(root: Path) -> list[Path]:
    return [
        root / "packages" / "titlemcp" / "src",
        root
        / "packages"
        / "jurisdictions"
        / "us"
        / "oh"
        / "franklin"
        / "recorder"
        / "src",
    ]


def prepend_paths(paths: Iterable[Path]) -> None:
    for path in reversed([str(path) for path in paths]):
        if path not in sys.path:
            sys.path.insert(0, path)


def main() -> None:
    root = repo_root()
    prepend_paths(local_src_paths(root))

    from titlemcp_us_oh_franklin_recorder.toolsets import FranklinAuditorToolset

    from title_mcp.mcp.server import create_mcp_server
    from title_mcp.platform import TitleMCPPlatform
    from title_mcp.settings import TitleMCPSettings

    settings = TitleMCPSettings(
        log_json=False,
        load_entry_point_adapters=False,
        load_entry_point_capabilities=False,
        load_entry_point_plugins=False,
        load_entry_point_sources=False,
        load_entry_point_toolsets=False,
        load_entry_point_vendors=False,
    )
    platform = TitleMCPPlatform(settings=settings)
    server = create_mcp_server(settings=settings, platform=platform)
    FranklinAuditorToolset().register(server, platform)

    LOGGER.info("Starting Franklin County Auditor MCP sample server")
    LOGGER.info("Repo root: %s", root)
    LOGGER.info("Transport: %s", settings.mcp_transport)
    LOGGER.info("Registered sample toolset: %s", FranklinAuditorToolset.toolset_id)

    server.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    os.environ.setdefault("TITLE_MCP_LOG_JSON", "false")
    main()

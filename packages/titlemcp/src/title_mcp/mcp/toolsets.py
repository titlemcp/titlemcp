from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from title_mcp.platform import TitleMCPPlatform


class TitleMCPToolset(Protocol):
    toolset_id: str

    def register(self, mcp: FastMCP, platform: TitleMCPPlatform) -> None:
        """Register MCP tools against a FastMCP server."""


def register_entry_point_toolsets(
    mcp: FastMCP,
    platform: TitleMCPPlatform,
    *,
    group: str = "title_mcp.toolsets",
) -> list[TitleMCPToolset]:
    toolsets: list[TitleMCPToolset] = []
    for entry_point in entry_points(group=group):
        toolset_cls = entry_point.load()
        toolset = toolset_cls()
        toolset.register(mcp, platform)
        toolsets.append(toolset)
    return toolsets

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from title_mcp.platform import TitleMCPPlatform
from titlemcp_platform_iasworld.tooling import register_auditor_tool
from titlemcp_us_oh_auditor.sites import OH_IASWORLD_SITES


class OhioAuditorToolset:
    """Registers one ``<county>_auditor_search`` MCP tool per configured county."""

    toolset_id = "us-oh-auditor"

    def register(self, mcp: FastMCP, platform: TitleMCPPlatform) -> None:
        for site in OH_IASWORLD_SITES:
            register_auditor_tool(mcp, platform, site)

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from title_mcp.mcp.tool_catalog import register_core_tools
from title_mcp.mcp.toolsets import register_entry_point_toolsets
from title_mcp.observability import configure_logging
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings, get_settings


def create_mcp_server(
    settings: TitleMCPSettings | None = None,
    platform: TitleMCPPlatform | None = None,
) -> FastMCP:
    settings = settings or (platform.settings if platform else get_settings())
    configure_logging(settings.log_level, json_logs=settings.log_json)
    platform = platform or TitleMCPPlatform(settings=settings)

    mcp = FastMCP(
        settings.app_name,
        instructions=(
            "Tools coordinate title and real estate service workflows. "
            "They are review-first and do not make autonomous legal decisions."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    register_core_tools(mcp, platform)
    if settings.load_entry_point_toolsets:
        register_entry_point_toolsets(mcp, platform)
    return mcp


def main() -> None:
    settings = get_settings()
    server = create_mcp_server(settings)
    server.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()

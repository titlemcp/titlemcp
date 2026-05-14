__all__ = [
    "TitleMCPToolset",
    "create_mcp_server",
    "register_core_tools",
    "register_entry_point_toolsets",
]


def __getattr__(name: str):
    if name == "create_mcp_server":
        from title_mcp.mcp.server import create_mcp_server

        return create_mcp_server
    if name == "register_core_tools":
        from title_mcp.mcp.tool_catalog import register_core_tools

        return register_core_tools
    if name in {"TitleMCPToolset", "register_entry_point_toolsets"}:
        from title_mcp.mcp.toolsets import TitleMCPToolset, register_entry_point_toolsets

        return {
            "TitleMCPToolset": TitleMCPToolset,
            "register_entry_point_toolsets": register_entry_point_toolsets,
        }[name]
    raise AttributeError(name)

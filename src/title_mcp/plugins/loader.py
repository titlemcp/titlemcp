from __future__ import annotations

from importlib.metadata import entry_points

from title_mcp.plugins.base import PluginContext, TitleMCPPlugin


def load_plugins(context: PluginContext, group: str = "title_mcp.plugins") -> list[TitleMCPPlugin]:
    plugins: list[TitleMCPPlugin] = []
    for entry_point in entry_points(group=group):
        plugin = entry_point.load()()
        plugin.register(context)
        plugins.append(plugin)
    return plugins

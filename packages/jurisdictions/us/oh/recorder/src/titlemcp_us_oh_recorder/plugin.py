from __future__ import annotations

from titlemcp_platform_publicsearch import build_recorder_source_connector

from title_mcp.plugins import PluginContext
from titlemcp_us_oh_recorder.sites import OH_PUBLICSEARCH_SITES


class OhioRecorderPlugin:
    """Registers one recorder source connector per configured Ohio county.

    A ``title_mcp.sources`` entry point registers one no-argument connector
    class, so the config-driven connectors are registered here instead.
    """

    name = "us-oh-recorder"

    def register(self, context: PluginContext) -> None:
        for site in OH_PUBLICSEARCH_SITES:
            if context.sources.get(site.source_id) is None:
                context.sources.register(build_recorder_source_connector(site))

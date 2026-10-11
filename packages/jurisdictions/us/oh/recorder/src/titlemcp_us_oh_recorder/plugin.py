from __future__ import annotations

from titlemcp_platform_countyfusion import build_recorder_source_connector as countyfusion
from titlemcp_platform_publicsearch import build_recorder_source_connector as publicsearch

from title_mcp.plugins import PluginContext
from titlemcp_us_oh_recorder.sites import OH_COUNTYFUSION_SITES, OH_PUBLICSEARCH_SITES


class OhioRecorderPlugin:
    """Registers one recorder source connector per configured Ohio county.

    A ``title_mcp.sources`` entry point registers one no-argument connector
    class, so the config-driven connectors are registered here instead.
    """

    name = "us-oh-recorder"

    def register(self, context: PluginContext) -> None:
        connectors = [publicsearch(site) for site in OH_PUBLICSEARCH_SITES] + [
            countyfusion(site) for site in OH_COUNTYFUSION_SITES
        ]
        for connector in connectors:
            if context.sources.get(connector.source_id) is None:
                context.sources.register(connector)

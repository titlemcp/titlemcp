from __future__ import annotations

from titlemcp_platform_publicsearch import build_recorder_source_connector

from title_mcp.plugins import PluginContext
from titlemcp_us_tx_recorder.sites import TX_RECORDER_SITES


class TexasRecorderPlugin:
    """Registers one recorder source connector per configured Texas county.

    A ``title_mcp.sources`` entry point registers one no-argument connector
    class, so the config-driven connectors are registered here instead.
    """

    name = "us-tx-recorder"

    def register(self, context: PluginContext) -> None:
        for site in TX_RECORDER_SITES:
            connector = build_recorder_source_connector(site)
            if context.sources.get(connector.source_id) is None:
                context.sources.register(connector)

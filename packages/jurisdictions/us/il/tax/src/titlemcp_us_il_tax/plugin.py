from __future__ import annotations

from title_mcp.plugins import PluginContext
from titlemcp_platform_iasworld import build_auditor_source_connector
from titlemcp_us_il_tax.sites import IL_TAX_SITES


class IllinoisTaxPlugin:
    """Registers one tax source connector per configured Illinois county.

    A ``title_mcp.sources`` entry point registers one no-argument connector
    class, so the config-driven connectors are registered here instead.
    """

    name = "us-il-tax"

    def register(self, context: PluginContext) -> None:
        for site in IL_TAX_SITES:
            if context.sources.get(site.source_id) is None:
                context.sources.register(build_auditor_source_connector(site))

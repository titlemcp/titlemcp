from __future__ import annotations

from title_mcp.plugins import PluginContext
from titlemcp_platform_iasworld import build_auditor_source_connector
from titlemcp_us_nm_tax.sites import NM_TAX_SITES


class NewMexicoTaxPlugin:
    """Registers one tax source connector per configured New Mexico county.

    A ``title_mcp.sources`` entry point registers one no-argument connector
    class, so the config-driven connectors are registered here instead.
    """

    name = "us-nm-tax"

    def register(self, context: PluginContext) -> None:
        for site in NM_TAX_SITES:
            if context.sources.get(site.source_id) is None:
                context.sources.register(build_auditor_source_connector(site))

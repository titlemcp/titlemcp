from __future__ import annotations

from title_mcp.plugins import PluginContext
from titlemcp_platform_iasworld import build_auditor_source_connector
from titlemcp_us_oh_auditor.sites import OH_IASWORLD_SITES


class OhioAuditorPlugin:
    """Registers one iasWorld auditor source connector per configured OH county.

    A single ``title_mcp.sources`` entry point can only register one no-arg
    connector class; the config-driven connectors are registered here instead so
    every county in ``OH_IASWORLD_SITES`` is wired up from one place.
    """

    name = "us-oh-auditor"

    def register(self, context: PluginContext) -> None:
        for site in OH_IASWORLD_SITES:
            if context.sources.get(site.source_id) is None:
                context.sources.register(build_auditor_source_connector(site))

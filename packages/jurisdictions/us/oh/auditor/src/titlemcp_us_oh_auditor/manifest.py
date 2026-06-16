from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_oh_auditor.sites import OH_IASWORLD_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-oh-auditor",
        name="Ohio County Auditor Property Search (iasWorld)",
        version="0.1.0",
        package_name="titlemcp-us-oh-auditor",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
            CapabilityType.MCP_TOOLSET,
        ],
        jurisdiction_scopes=[site.jurisdiction_scope for site in OH_IASWORLD_SITES],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": (
                "titlemcp_us_oh_auditor.adapters:OhioCountyAuditorAdapter"
            ),
            "title_mcp.plugins": "titlemcp_us_oh_auditor.plugin:OhioAuditorPlugin",
            "title_mcp.toolsets": "titlemcp_us_oh_auditor.toolsets:OhioAuditorToolset",
        },
        review_required=True,
        metadata={
            "platform": "tyler-iasworld",
            "sources": [site.source_id for site in OH_IASWORLD_SITES],
            "counties": [site.county for site in OH_IASWORLD_SITES],
            "auditor_search_modes": ["address", "owner", "parid"],
        },
    )

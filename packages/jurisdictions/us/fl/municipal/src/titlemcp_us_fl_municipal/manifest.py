from __future__ import annotations

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-fl-municipal",
        name="Florida Municipal Lien Directory",
        version="0.1.0",
        package_name="titlemcp-us-fl-municipal",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[JurisdictionScope(country="US", state="FL")],
        workflow_kinds=[WorkflowKind.MUNICIPAL_LIEN_SEARCH],
        entry_points={
            "title_mcp.adapters": (
                "titlemcp_us_fl_municipal.adapters:FloridaMunicipalLienSearchAdapter"
            ),
            "title_mcp.sources": "titlemcp_us_fl_municipal.connector:FloridaMunicipalDirectory",
        },
        review_required=True,
        metadata={"sources": ["us-fl-municipal-directory"]},
    )

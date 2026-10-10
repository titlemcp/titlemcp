from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_oh_recorder.sites import OH_PUBLICSEARCH_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-oh-recorder",
        name="Ohio County Recorders",
        version="0.1.0",
        package_name="titlemcp-us-oh-recorder",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.scope for site in OH_PUBLICSEARCH_SITES],
        workflow_kinds=[WorkflowKind.RELEASE_TRACKING],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_oh_recorder.adapters:OhioReleaseTrackingAdapter",
            "title_mcp.plugins": "titlemcp_us_oh_recorder.plugin:OhioRecorderPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["kofile-publicsearch"],
            "sources": [site.source_id for site in OH_PUBLICSEARCH_SITES],
            "counties": [site.county for site in OH_PUBLICSEARCH_SITES],
        },
    )

from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_il_recorder.sites import IL_RECORDER_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-il-recorder",
        name="Illinois County Clerks",
        version="0.1.0",
        package_name="titlemcp-us-il-recorder",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.scope for site in IL_RECORDER_SITES],
        workflow_kinds=[WorkflowKind.RELEASE_TRACKING],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_il_recorder.adapters:IllinoisReleaseTrackingAdapter",
            "title_mcp.plugins": "titlemcp_us_il_recorder.plugin:IllinoisRecorderPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["kofile-publicsearch"],
            "sources": [site.source_id for site in IL_RECORDER_SITES],
            "counties": [site.county for site in IL_RECORDER_SITES],
        },
    )

from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_pa_recorder.sites import PA_RECORDER_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-pa-recorder",
        name="Pennsylvania Recorders of Deeds",
        version="0.1.0",
        package_name="titlemcp-us-pa-recorder",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.scope for site in PA_RECORDER_SITES],
        workflow_kinds=[WorkflowKind.RELEASE_TRACKING],
        entry_points={
            "title_mcp.adapters": (
                "titlemcp_us_pa_recorder.adapters:PennsylvaniaReleaseTrackingAdapter"
            ),
            "title_mcp.plugins": "titlemcp_us_pa_recorder.plugin:PennsylvaniaRecorderPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["kofile-publicsearch"],
            "sources": [site.source_id for site in PA_RECORDER_SITES],
            "counties": [site.county for site in PA_RECORDER_SITES],
        },
    )

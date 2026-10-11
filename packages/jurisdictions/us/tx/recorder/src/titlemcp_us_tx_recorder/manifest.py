from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_tx_recorder.sites import TX_RECORDER_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-tx-recorder",
        name="Texas County Clerks",
        version="0.1.0",
        package_name="titlemcp-us-tx-recorder",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.scope for site in TX_RECORDER_SITES],
        workflow_kinds=[WorkflowKind.RELEASE_TRACKING],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_tx_recorder.adapters:TexasReleaseTrackingAdapter",
            "title_mcp.plugins": "titlemcp_us_tx_recorder.plugin:TexasRecorderPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["kofile-publicsearch"],
            "sources": [site.source_id for site in TX_RECORDER_SITES],
            "counties": [site.county for site in TX_RECORDER_SITES],
        },
    )

from __future__ import annotations

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-oh-franklin-recorder",
        name="Franklin County, Ohio Recorder",
        version="0.1.0",
        package_name="titlemcp-us-oh-franklin-recorder",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[
            JurisdictionScope(country="US", state="OH", county="Franklin County")
        ],
        workflow_kinds=[WorkflowKind.PUBLIC_RECORDS_SEARCH],
        entry_points={
            "title_mcp.adapters": (
                "titlemcp_us_oh_franklin_recorder.adapters:"
                "FranklinCountyOhioRecorderAdapter"
            ),
            "title_mcp.sources": (
                "titlemcp_us_oh_franklin_recorder.sources:"
                "FranklinRecorderSourceConnector"
            ),
        },
        review_required=True,
        metadata={
            "sources": [
                "us-oh-franklin-recorder",
            ],
        },
    )

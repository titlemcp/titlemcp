from __future__ import annotations

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-dc-tax",
        name="District of Columbia Real Property Tax",
        version="0.1.0",
        package_name="titlemcp-us-dc-tax",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[JurisdictionScope(country="US", state="DC")],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": (
                "titlemcp_us_dc_tax.adapters:DistrictOfColumbiaTaxCertificateAdapter"
            ),
            "title_mcp.sources": "titlemcp_us_dc_tax.connector:DistrictOfColumbiaTaxConnector",
        },
        review_required=True,
        metadata={
            "sources": ["us-dc-otr-tax"],
            "dataset": "Integrated Tax System Public Extract",
            "license": "CC BY 4.0",
        },
    )

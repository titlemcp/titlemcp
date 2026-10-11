from __future__ import annotations

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-tn-tax",
        name="Tennessee County Trustees",
        version="0.1.0",
        package_name="titlemcp-us-tn-tax",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[JurisdictionScope(country="US", state="TN", county="Shelby County")],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_tn_tax.adapters:ShelbyCountyTaxCertificateAdapter",
            "title_mcp.sources": "titlemcp_us_tn_tax.connector:ShelbyCountyTaxConnector",
        },
        review_required=True,
        metadata={
            "sources": ["us-tn-shelby-tax"],
            "counties": ["Shelby County"],
        },
    )

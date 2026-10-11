from __future__ import annotations

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-ca-tax",
        name="California County Tax Collectors",
        version="0.1.0",
        package_name="titlemcp-us-ca-tax",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[
            JurisdictionScope(country="US", state="CA", county="Contra Costa County")
        ],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_ca_tax.adapters:ContraCostaTaxCertificateAdapter",
            "title_mcp.sources": "titlemcp_us_ca_tax.connector:ContraCostaTaxConnector",
        },
        review_required=True,
        metadata={
            "sources": ["us-ca-contra-costa-tax"],
            "counties": ["Contra Costa County"],
        },
    )

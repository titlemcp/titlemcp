from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_nm_tax.sites import NM_TAX_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-nm-tax",
        name="New Mexico County Tax Collectors",
        version="0.1.0",
        package_name="titlemcp-us-nm-tax",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.jurisdiction_scope for site in NM_TAX_SITES],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_nm_tax.adapters:NewMexicoTaxCertificateAdapter",
            "title_mcp.plugins": "titlemcp_us_nm_tax.plugin:NewMexicoTaxPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["tyler-iasworld"],
            "sources": [site.source_id for site in NM_TAX_SITES],
            "counties": [site.county for site in NM_TAX_SITES],
        },
    )

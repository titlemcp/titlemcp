from __future__ import annotations

from title_mcp.capabilities import CapabilityManifest, CapabilityType
from title_mcp.domain.models import WorkflowKind
from titlemcp_us_pa_tax.sites import PA_TAX_SITES


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="us-pa-tax",
        name="Pennsylvania County Tax Collectors",
        version="0.1.0",
        package_name="titlemcp-us-pa-tax",
        capability_types=[
            CapabilityType.WORKFLOW_ADAPTER,
            CapabilityType.GOVERNMENT_SOURCE,
        ],
        jurisdiction_scopes=[site.jurisdiction_scope for site in PA_TAX_SITES],
        workflow_kinds=[WorkflowKind.TAX_CERTIFICATE],
        entry_points={
            "title_mcp.adapters": "titlemcp_us_pa_tax.adapters:PennsylvaniaTaxCertificateAdapter",
            "title_mcp.plugins": "titlemcp_us_pa_tax.plugin:PennsylvaniaTaxPlugin",
        },
        review_required=True,
        metadata={
            "platforms": ["tyler-iasworld"],
            "sources": [site.source_id for site in PA_TAX_SITES],
            "counties": [site.county for site in PA_TAX_SITES],
        },
    )

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.domain.title import TitleMatterSnapshot


class VendorKind(StrEnum):
    HOA_ESTOPPEL = "hoa_estoppel"
    MUNICIPAL_LIEN = "municipal_lien"
    TAX_CERTIFICATE = "tax_certificate"
    PAYOFF = "payoff"
    RELEASE_TRACKING = "release_tracking"
    DOCUMENT_OCR = "document_ocr"
    TITLE_PRODUCTION = "title_production"
    UNDERWRITER = "underwriter"


class VendorOrderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    WAITING_ON_CLIENT = "waiting_on_client"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class VendorDescriptor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_id: str
    name: str
    kind: VendorKind
    jurisdiction_scopes: list[JurisdictionScope] = Field(default_factory=list)
    priority: int = 0
    requires_auth: bool = True
    supports_workflow_kinds: list[WorkflowKind] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorOrderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    workflow_id: str | None = None
    kind: VendorKind
    jurisdiction: Jurisdiction
    title_matter: TitleMatterSnapshot
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "system"


class VendorOrderResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_id: str
    status: VendorOrderStatus
    external_order_id: str | None = None
    message: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorConnector(Protocol):
    vendor_id: str
    descriptor: VendorDescriptor

    def supports(self, jurisdiction: Jurisdiction, kind: VendorKind | None = None) -> bool:
        """Return true when this connector can service the jurisdiction."""

    async def submit_order(self, request: VendorOrderRequest) -> VendorOrderResult:
        """Submit or stage a vendor order in a review-first manner."""

    async def get_status(self, external_order_id: str) -> VendorOrderResult:
        """Fetch current vendor status for an existing order."""

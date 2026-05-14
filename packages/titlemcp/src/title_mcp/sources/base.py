from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class SourceKind(StrEnum):
    COUNTY_RECORDER = "county_recorder"
    OFFICIAL_RECORDS = "official_records"
    COURT = "court"
    TAX_AUTHORITY = "tax_authority"
    MUNICIPAL = "municipal"
    HOA = "hoa"
    UNDERWRITER = "underwriter"
    VENDOR_API = "vendor_api"
    DOCUMENT_OCR = "document_ocr"


class SourceResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NO_RESULTS = "no_results"
    REQUIRES_CONFIGURATION = "requires_configuration"
    FAILED = "failed"


class SourceCitation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str
    uri: str | None = None
    recording_reference: str | None = None
    retrieved_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDescriptor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    name: str
    kind: SourceKind
    jurisdiction_scope: JurisdictionScope
    priority: int = 0
    owner: str | None = None
    base_url: str | None = None
    requires_auth: bool = False
    supports_workflow_kinds: list[WorkflowKind] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    jurisdiction: Jurisdiction
    kind: SourceKind
    criteria: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None
    requested_by: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    status: SourceResultStatus
    records: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_reference: str | None = None
    requires_human_review: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceConnector(Protocol):
    source_id: str
    descriptor: SourceDescriptor

    def supports(self, jurisdiction: Jurisdiction, kind: SourceKind | None = None) -> bool:
        """Return true when this connector can query the source for the jurisdiction."""

    async def query(self, query: SourceQuery) -> SourceResult:
        """Query a government, public-record, vendor, OCR, or other operational source."""

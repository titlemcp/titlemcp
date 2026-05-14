from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class WorkflowKind(StrEnum):
    DOCUMENT_ANALYSIS = "document_analysis"
    PUBLIC_RECORDS_SEARCH = "public_records_search"
    HOA_ESTOPPEL = "hoa_estoppel"
    MUNICIPAL_LIEN_SEARCH = "municipal_lien_search"
    TAX_CERTIFICATE = "tax_certificate"
    RELEASE_TRACKING = "release_tracking"
    PAYOFF_PARSING = "payoff_parsing"
    TITLE_CURATIVE = "title_curative"
    DOCUMENT_CLASSIFICATION = "document_classification"
    CHECKLIST_PACKET = "checklist_packet"
    STATUS_TRACKING = "status_tracking"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_ON_EXTERNAL = "waiting_on_external"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    LEGAL_REVIEW_REQUIRED = "legal_review_required"


class AuditActor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    actor_id: str = "system"
    actor_type: Literal["system", "user", "llm", "external_service"] = "system"
    display_name: str | None = None


class Address(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class Jurisdiction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    country: str = Field(default="US", min_length=2, max_length=2)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    county: str | None = None
    municipality: str | None = None

    @field_validator("country", "state")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @property
    def key(self) -> str:
        parts = [self.country]
        if self.state:
            parts.append(self.state)
        if self.county:
            parts.append(_key_part(self.county))
        if self.municipality:
            parts.append(_key_part(self.municipality))
        return ":".join(parts)

    def matches(
        self,
        *,
        country: str | None = None,
        state: str | None = None,
        county: str | None = None,
        municipality: str | None = None,
    ) -> bool:
        expected = Jurisdiction(
            country=country or self.country,
            state=state,
            county=county,
            municipality=municipality,
        )
        if country and self.country != expected.country:
            return False
        if state and self.state != expected.state:
            return False
        if county and _name_key(self.county) != _name_key(expected.county):
            return False
        if municipality and _name_key(self.municipality) != _name_key(expected.municipality):
            return False
        return True


def _key_part(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _name_key(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.replace("-", " ").lower().split())


class OrderRef(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_number: str = Field(min_length=1)
    property_address: Address | None = None
    buyer: str | None = None
    seller: str | None = None
    closing_date: datetime | None = None
    external_refs: dict[str, str] = Field(default_factory=dict)


class WorkflowAction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("action"))
    label: str
    description: str | None = None
    action_type: str = "manual_or_external"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTask(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    name: str
    status: TaskStatus = TaskStatus.QUEUED
    action_type: str = "manual_or_external"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class HumanReviewRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("review"))
    status: ReviewStatus = ReviewStatus.PENDING
    risk_level: RiskLevel = RiskLevel.MEDIUM
    prompt: str
    reviewer: str | None = None
    decision_notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit"))
    workflow_id: str
    action: str
    actor: AuditActor = Field(default_factory=AuditActor)
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowRequest(BaseModel):
    kind: WorkflowKind
    order: OrderRef
    jurisdiction: Jurisdiction
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: AuditActor = Field(default_factory=AuditActor)
    require_human_review: bool = True


class WorkflowRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wf"))
    kind: WorkflowKind
    status: WorkflowStatus = WorkflowStatus.QUEUED
    order: OrderRef
    jurisdiction: Jurisdiction
    payload: dict[str, Any] = Field(default_factory=dict)
    adapter_id: str | None = None
    tasks: list[WorkflowTask] = Field(default_factory=list)
    review: HumanReviewRequest | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    audit: list[AuditEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def add_audit(
        self,
        action: str,
        actor: AuditActor | None = None,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.audit.append(
            AuditEvent(
                workflow_id=self.id,
                action=action,
                actor=actor or AuditActor(),
                payload=payload or {},
                trace_id=trace_id,
            )
        )
        self.updated_at = utc_now()

    def touch(self) -> None:
        self.updated_at = utc_now()

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.domain.models import Address
from title_mcp.domain.title import RecordingReference


class ExamSheetKind(StrEnum):
    """The abstractor summary sheets that make up a scanned title exam package."""

    SEARCH_COVER = "search_cover"
    TAX = "tax"
    MORTGAGES = "mortgages"
    EXCEPTIONS = "exceptions"
    JUDGMENTS = "judgments"
    CHAIN_OF_TITLE = "chain_of_title"
    INDEX_SUMMARY = "index_summary"


class ExtractionConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExceptionInstrumentKind(StrEnum):
    EASEMENT = "easement"
    RIGHT_OF_WAY = "right_of_way"
    LEASE = "lease"
    AGREEMENT = "agreement"
    RESTRICTION = "restriction"
    PLAT = "plat"


class FieldProvenance(BaseModel):
    """Where an extracted entry came from, so a reviewer can click through to the scan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sheet: ExamSheetKind
    src_page: int = Field(ge=1)
    src_text: str | None = None
    confidence: ExtractionConfidence = ExtractionConfidence.LOW

    @property
    def is_trusted(self) -> bool:
        return self.confidence == ExtractionConfidence.HIGH


class MortgageEntry(BaseModel):
    """One row of the abstractor's MORTGAGES sheet. Destined for Schedule B, Part I."""

    model_config = ConfigDict(str_strip_whitespace=True)

    recording: RecordingReference
    borrowers: str = Field(min_length=1)
    lender: str = Field(min_length=1)
    original_amount: Decimal | None = None
    executed_date: date | None = None
    maturity_date: date | None = None
    prior_owner: bool = False
    heloc: bool = False
    notes: str | None = None
    provenance: FieldProvenance


class ExceptionEntry(BaseModel):
    """One row of the abstractor's EXCEPTION SHEET. Destined for Schedule B, Part II."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_kinds: list[ExceptionInstrumentKind] = Field(min_length=1)
    recording: RecordingReference
    first_party: str = Field(min_length=1)
    second_party: str = Field(min_length=1)
    executed_date: date | None = None
    instrument_name: str | None = None
    notes: str | None = None
    provenance: FieldProvenance


class JudgmentEntry(BaseModel):
    """One row of the abstractor's judgment-lien sheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    debtor: str = Field(min_length=1)
    creditor: str = Field(min_length=1)
    case_number: str | None = None
    court: str | None = None
    amount: Decimal | None = None
    recording: RecordingReference | None = None
    provenance: FieldProvenance


class TaxParcelEntry(BaseModel):
    """Per-parcel tax status taken from the abstractor's tax worksheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str = Field(min_length=1)
    tax_year: int = Field(ge=1900, le=2200)
    taxpayer_name: str | None = None
    first_half_amount: Decimal | None = None
    first_half_paid: bool = False
    second_half_amount: Decimal | None = None
    second_half_paid: bool = False
    special_assessment_amount: Decimal | None = None
    special_assessment_paid: bool = False
    special_assessment_label: str | None = None
    cauv: bool = False
    provenance: FieldProvenance


class SearchCoverSheet(BaseModel):
    """The abstractor's cover sheet.

    This carries the declared counts that make the package self-checking: the
    abstractor states how many mortgages, judgments, and exceptions the file has,
    independently of the detail sheets that enumerate them.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    order_number: str = Field(min_length=1)
    county: str | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    auditor_owners: str | None = None
    buyers: str | None = None
    property_address: Address | None = None
    search_start_date: date | None = None
    completed_date: date | None = None
    completed_by: str | None = None
    last_shown_owner_transfer: RecordingReference | None = None
    declared_mortgage_count: int = Field(ge=0)
    declared_judgment_count: int = Field(ge=0)
    declared_exception_count: int = Field(ge=0)
    matters_of_concern: list[str] = Field(default_factory=list)
    provenance: FieldProvenance

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class IndexSummarySheet(BaseModel):
    """The abstractor's index page.

    A third statement of the same facts: book/page references gathered while
    searching, before they were written onto the detail sheets. Cross-checking it
    against the detail sheets catches transcription drift in either direction.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    mortgages: list[RecordingReference] = Field(default_factory=list)
    leases_agreements: list[RecordingReference] = Field(default_factory=list)
    easements_rights_of_way: list[RecordingReference] = Field(default_factory=list)
    name_searches: list[str] = Field(default_factory=list)
    provenance: FieldProvenance


class ExamPackage(BaseModel):
    """Canonical record for one scanned abstractor title exam package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.exam_package"
    schema_version: str = "1.0"
    record_type: str = "exam_package"
    source: dict[str, Any] = Field(default_factory=dict)
    file_number: str = Field(min_length=1)
    cover: SearchCoverSheet
    mortgages: list[MortgageEntry] = Field(default_factory=list)
    exceptions: list[ExceptionEntry] = Field(default_factory=list)
    judgments: list[JudgmentEntry] = Field(default_factory=list)
    tax_parcels: list[TaxParcelEntry] = Field(default_factory=list)
    index: IndexSummarySheet | None = None
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)

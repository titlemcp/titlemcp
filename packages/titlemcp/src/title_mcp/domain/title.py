from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.domain.models import Address


class PartyRole(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"
    BORROWER = "borrower"
    LENDER = "lender"
    OWNER = "owner"
    HOA = "hoa"
    MUNICIPALITY = "municipality"
    COUNTY_OFFICE = "county_office"
    VENDOR = "vendor"
    UNDERWRITER = "underwriter"
    CLOSER = "closer"
    EXAMINER = "examiner"
    ATTORNEY = "attorney"
    OTHER = "other"


class ContactPoint(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: Address | None = None
    reference: str | None = None


class TitleParty(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: PartyRole
    name: str = Field(min_length=1)
    contact: ContactPoint | None = None
    external_refs: dict[str, str] = Field(default_factory=dict)


class ParcelIdentifier(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str = Field(min_length=1)
    county: str | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    tax_authority: str | None = None
    alternate_ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class LegalDescription(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1)
    source_document_id: str | None = None
    parsed_components: dict[str, Any] = Field(default_factory=dict)


class RecordingReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_number: str | None = None
    book: str | None = None
    page: str | None = None
    recorded_date: date | None = None
    recording_office: str | None = None
    document_type: str | None = None

    @property
    def display(self) -> str:
        if self.instrument_number:
            return self.instrument_number
        if self.book or self.page:
            return "/".join(part for part in [self.book, self.page] if part)
        return "unrecorded"


class DocumentReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str | None = None
    uri: str | None = None
    document_type: str | None = None
    recording: RecordingReference | None = None
    received_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LienReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    lien_id: str | None = None
    lienholder: TitleParty | None = None
    original_amount: Decimal | None = None
    recording: RecordingReference | None = None
    payoff_document: DocumentReference | None = None
    release_recording: RecordingReference | None = None


class PayoffTerms(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    lender_name: str | None = None
    payoff_amount: Decimal | None = None
    good_through_date: date | None = None
    per_diem: Decimal | None = None
    wire_instructions_document_id: str | None = None
    requires_wire_review: bool = True
    exceptions: list[str] = Field(default_factory=list)


class VendorReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_id: str
    order_id: str | None = None
    status: str | None = None
    portal_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TitleMatterSnapshot(BaseModel):
    """Portable title-order context shared by tools, adapters, vendors, and UIs."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file_number: str = Field(min_length=1)
    property_address: Address | None = None
    parcels: list[ParcelIdentifier] = Field(default_factory=list)
    legal_descriptions: list[LegalDescription] = Field(default_factory=list)
    parties: list[TitleParty] = Field(default_factory=list)
    documents: list[DocumentReference] = Field(default_factory=list)
    liens: list[LienReference] = Field(default_factory=list)
    vendors: list[VendorReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

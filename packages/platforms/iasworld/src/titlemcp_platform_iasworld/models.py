from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from titlemcp_platform_iasworld.config import AuditorSearchMode, _normalize_mode


class IasWorldAuditorSearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: AuditorSearchMode | str = AuditorSearchMode.ADDRESS
    parcel_id: str | None = None
    owner_name: str | None = None
    address: str | None = None
    address_number: str | int | None = None
    street_name: str | None = None
    street_direction: str | None = None
    unit: str | None = None
    page_number: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=50)
    include_details: bool = True
    max_results: int = Field(default=10, ge=1, le=50)
    max_detail_records: int = Field(default=1, ge=0, le=10)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: str | AuditorSearchMode) -> AuditorSearchMode:
        return _normalize_mode(value)


class IasWorldAuditorSearchHit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str | None = None
    parcel_number: str | None = None
    parcel_token: str | None = None
    jurisdiction: str | None = None
    tax_year: str | None = None
    address: str | None = None
    owner: str | None = None
    legal_description: str | None = None
    detail_url: str | None = None
    raw_cells: list[str] = Field(default_factory=list)


class IasWorldAuditorParcelDetail(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str | None = None
    parcel_number: str | None = None
    parcel_token: str | None = None
    jurisdiction: str | None = None
    tax_year: str | None = None
    map_routing: str | None = None
    owner_display: str | None = None
    site_address: str | None = None
    permalink: str | None = None
    owners: list[str] = Field(default_factory=list)
    owner_mailing_address: list[str] = Field(default_factory=list)
    site_property_address: str | None = None
    legal_description: list[str] = Field(default_factory=list)
    legal_acres: str | None = None
    most_recent_transfer: dict[str, Any] = Field(default_factory=dict)
    tax_status: dict[str, Any] = Field(default_factory=dict)
    appraised_value: dict[str, Any] = Field(default_factory=dict)
    taxable_value: dict[str, Any] = Field(default_factory=dict)
    annual_taxes: dict[str, Any] = Field(default_factory=dict)
    dwelling_data: dict[str, Any] = Field(default_factory=dict)
    site_data: dict[str, Any] = Field(default_factory=dict)
    sections: dict[str, Any] = Field(default_factory=dict)
    raw_section_rows: dict[str, list[list[str]]] = Field(default_factory=dict)
    source_url: str | None = None
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class IasWorldAuditorSearchResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: IasWorldAuditorSearchQuery
    search_url: str
    search_mode: AuditorSearchMode
    result_count: int
    results: list[IasWorldAuditorSearchHit] = Field(default_factory=list)
    details: list[IasWorldAuditorParcelDetail] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

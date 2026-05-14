from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.models import Address, Jurisdiction


class MoneyAmount(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display: str | None = None
    value: Decimal | None = None
    currency: str = "USD"


class PropertyAssessmentSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    source_name: str | None = None
    source_url: str | None = None
    search_url: str | None = None
    detail_url: str | None = None
    retrieved_at: str | None = None


class PropertyAssessmentSearchContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: str | None = None
    query: dict[str, Any] = Field(default_factory=dict)
    result_count: int | None = None
    result_index: int | None = None
    result_hit: dict[str, Any] | None = None


class PropertyAssessmentParcel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str | None = None
    parcel_number: str | None = None
    normalized_parcel_id: str | None = None
    parcel_token: str | None = None
    tax_authority_parcel_token: str | None = None
    tax_authority_jurisdiction: str | None = None
    tax_year: str | None = None
    map_routing: str | None = None
    permalink: str | None = None
    alternate_ids: dict[str, str] = Field(default_factory=dict)


class PropertyAssessmentOwnership(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner_display: str | None = None
    owners: list[str] = Field(default_factory=list)
    mailing_address: Address | None = None
    mailing_address_lines: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentProperty(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    site_address_display: str | None = None
    site_address: Address | None = None
    site_address_lines: list[str] = Field(default_factory=list)
    legal_description_lines: list[str] = Field(default_factory=list)
    legal_description_text: str | None = None
    legal_acres: Decimal | None = None
    property_class: str | None = None
    land_use: str | None = None
    tax_district: str | None = None
    school_district: str | None = None
    municipality: str | None = None
    township: str | None = None
    appraisal_neighborhood: str | None = None
    postal_code: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentTransfer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transfer_date: str | None = None
    transfer_price: MoneyAmount | None = None
    instrument_type: str | None = None
    parcel_count: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentTaxStatus(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tax_year: str | None = None
    property_class: str | None = None
    land_use: str | None = None
    tax_district: str | None = None
    school_district: str | None = None
    municipality: str | None = None
    township: str | None = None
    appraisal_neighborhood: str | None = None
    postal_code: str | None = None
    tax_lien: bool | None = None
    cdq: bool | None = None
    cauv_property: bool | None = None
    owner_occupancy_credit: dict[str, bool] = Field(default_factory=dict)
    homestead_credit: dict[str, bool] = Field(default_factory=dict)
    rental_registration: bool | None = None
    rental_exception: bool | None = None
    board_of_revision: bool | None = None
    pending_exemption: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentValueLine(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str
    land: MoneyAmount | None = None
    improvements: MoneyAmount | None = None
    total: MoneyAmount | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentValueTable(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    value_type: Literal["appraised", "taxable"]
    tax_year: str | None = None
    rows: list[PropertyAssessmentValueLine] = Field(default_factory=list)
    summary: dict[str, PropertyAssessmentValueLine] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentValuation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    appraised: PropertyAssessmentValueTable | None = None
    taxable: PropertyAssessmentValueTable | None = None


class PropertyAssessmentAnnualTax(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tax_year: str | None = None
    net_annual_tax: MoneyAmount | None = None
    total_paid: MoneyAmount | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentTaxSummary(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    annual: list[PropertyAssessmentAnnualTax] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentDwelling(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    year_built: int | None = None
    total_finished_area_sqft: int | None = None
    rooms: int | None = None
    bedrooms: int | None = None
    full_baths: int | None = None
    half_baths: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentSite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    frontage_feet: Decimal | None = None
    depth_feet: Decimal | None = None
    acres: Decimal | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyAssessmentRecord(BaseModel):
    """Canonical property assessment record shared by county auditor sources."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.property_assessment_record"
    schema_version: str = "1.0"
    record_type: Literal["property_assessment"] = "property_assessment"
    source: PropertyAssessmentSource
    jurisdiction: Jurisdiction
    search: PropertyAssessmentSearchContext = Field(
        default_factory=PropertyAssessmentSearchContext
    )
    parcel: PropertyAssessmentParcel = Field(default_factory=PropertyAssessmentParcel)
    ownership: PropertyAssessmentOwnership = Field(default_factory=PropertyAssessmentOwnership)
    property: PropertyAssessmentProperty = Field(default_factory=PropertyAssessmentProperty)
    transfer: PropertyAssessmentTransfer | None = None
    tax_status: PropertyAssessmentTaxStatus = Field(default_factory=PropertyAssessmentTaxStatus)
    valuation: PropertyAssessmentValuation = Field(default_factory=PropertyAssessmentValuation)
    taxes: PropertyAssessmentTaxSummary = Field(default_factory=PropertyAssessmentTaxSummary)
    dwelling: PropertyAssessmentDwelling | None = None
    site: PropertyAssessmentSite | None = None
    source_specific: dict[str, Any] = Field(default_factory=dict)

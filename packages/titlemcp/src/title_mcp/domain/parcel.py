from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.auditor import MoneyAmount
from title_mcp.domain.models import Address, Jurisdiction


class ParcelRecordSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    source_name: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    duration_seconds: float | None = None


class ParcelSearchContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: dict[str, Any] = Field(default_factory=dict)
    normalized_query: str | None = None
    result_count: int | None = None
    result_index: int | None = None
    result_hit: dict[str, Any] | None = None


class ParcelIdentifiers(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str | None = None
    parcel_number: str | None = None
    normalized_parcel_number: str | None = None
    account_number: str | None = None
    tax_id: str | None = None
    stable_id_field: str | None = None
    uuid: str | None = None
    stack_uuid: str | None = None
    path: str | None = None
    alternate_ids: dict[str, str] = Field(default_factory=dict)


class ParcelOwnership(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner_display: str | None = None
    owners: list[str] = Field(default_factory=list)
    mailing_address: Address | None = None
    mailing_address_lines: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelSite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    address_display: str | None = None
    address: Address | None = None
    legal_description: str | None = None
    acreage_deeded: Decimal | None = None
    acreage_gis: Decimal | None = None
    acreage_regrid: Decimal | None = None
    square_feet_gis: Decimal | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelLandUse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_class: str | None = None
    use_code: str | None = None
    use_description: str | None = None
    zoning_code: str | None = None
    zoning_description: str | None = None
    zoning_type: str | None = None
    zoning_subtype: str | None = None
    zoning_code_link: str | None = None
    owner_occupied: bool | None = None
    homestead_exemption: bool | None = None
    rental: bool | None = None
    cauv: bool | None = None
    qualified_opportunity_zone: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelValuation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    value_type: str | None = None
    land_value: MoneyAmount | None = None
    improvement_value: MoneyAmount | None = None
    total_value: MoneyAmount | None = None
    agricultural_value: MoneyAmount | None = None
    sale_price: MoneyAmount | None = None
    sale_date: str | None = None
    last_transfer_date: str | None = None
    tax_amount: MoneyAmount | None = None
    tax_year: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelBuilding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    year_built: int | None = None
    effective_year_built: str | None = None
    stories: Decimal | None = None
    units: int | None = None
    rooms: Decimal | None = None
    bedrooms: int | None = None
    full_baths: Decimal | None = None
    half_baths: Decimal | None = None
    total_baths: Decimal | None = None
    building_area_sqft: Decimal | None = None
    building_area_definition: str | None = None
    style: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelGeography(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    latitude: Decimal | None = None
    longitude: Decimal | None = None
    centroid: dict[str, Any] | None = None
    geometry: dict[str, Any] | None = None
    geoid: str | None = None
    census_tract: str | None = None
    census_block: str | None = None
    census_block_group: str | None = None
    census_zcta: str | None = None
    school_district: str | None = None
    plss_township: str | None = None
    plss_section: str | None = None
    plss_range: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParcelRecord(BaseModel):
    """Canonical parcel record shared by parcel data providers."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.parcel_record"
    schema_version: str = "1.0"
    record_type: Literal["parcel"] = "parcel"
    source: ParcelRecordSource
    jurisdiction: Jurisdiction
    search: ParcelSearchContext = Field(default_factory=ParcelSearchContext)
    identifiers: ParcelIdentifiers = Field(default_factory=ParcelIdentifiers)
    ownership: ParcelOwnership = Field(default_factory=ParcelOwnership)
    site: ParcelSite = Field(default_factory=ParcelSite)
    land_use: ParcelLandUse = Field(default_factory=ParcelLandUse)
    valuation: ParcelValuation = Field(default_factory=ParcelValuation)
    building: ParcelBuilding | None = None
    geography: ParcelGeography = Field(default_factory=ParcelGeography)
    source_specific: dict[str, Any] = Field(default_factory=dict)

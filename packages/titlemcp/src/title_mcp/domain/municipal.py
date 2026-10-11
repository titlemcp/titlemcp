"""Where a local government's liens, permits and code cases are asked about.

A municipal lien search asks a city or county what is owed on a parcel that the
official records don't show yet: code violations and code liens, open or expired
permits, utility balances and special assessments. Each government answers in
its own way. Some sell a lien letter through a vendor's portal, some take a form
by email, some treat it as a public records request. These models are one
directory entry per government, as its own pages describe the process.

An entry is what a government published on the day it was read. Fees and
processes change, so every answer is marked for human review.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.models import Jurisdiction


class GovernmentKind(StrEnum):
    COUNTY = "county"
    MUNICIPALITY = "municipality"


class Offered(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class LienOrderChannel(StrEnum):
    """How the government's pages say to ask for a lien letter."""

    ONLINE_PORTAL = "online_portal"
    EMAIL = "email"
    FORM_EMAIL = "form_email"
    MAIL = "mail"
    FAX = "fax"
    PHONE = "phone"
    IN_PERSON = "in_person"
    RECORDS_PORTAL = "records_portal"
    NONE_FOUND = "none_found"


class LienCoverage(StrEnum):
    CODE_VIOLATIONS = "code_violations"
    CODE_LIENS = "code_liens"
    OPEN_PERMITS = "open_permits"
    EXPIRED_PERMITS = "expired_permits"
    UTILITIES = "utilities"
    SOLID_WASTE = "solid_waste"
    STORMWATER = "stormwater"
    SPECIAL_ASSESSMENTS = "special_assessments"
    RECORDED_LIENS = "recorded_liens"
    FALSE_ALARM = "false_alarm"
    OTHER = "other"


class PermitPlatform(StrEnum):
    """The software behind a government's public permit search."""

    ACCELA = "accela"
    ENERGOV = "energov"
    CENTRALSQUARE = "centralsquare"
    CITIZENSERVE = "citizenserve"
    MYGOVERNMENTONLINE = "mygovernmentonline"
    IWORQ = "iworq"
    IN_HOUSE = "in_house"
    OTHER = "other"
    UNKNOWN = "unknown"


class BalanceRequest(StrEnum):
    """How a title agent learns a utility balance."""

    IN_LIEN_LETTER = "in_lien_letter"
    SEPARATE_REQUEST = "separate_request"
    NOT_OFFERED = "not_offered"
    UNKNOWN = "unknown"


class AssessmentBilling(StrEnum):
    TAX_BILL = "tax_bill"
    DIRECT = "direct"
    BOTH = "both"
    NONE_FOUND = "none_found"


class Confidence(StrEnum):
    #: Read on the government's own pages.
    HIGH = "high"
    #: Read on a vendor's page, or on a copy of the government's page.
    MEDIUM = "medium"
    LOW = "low"


class LienLetter(BaseModel):
    """The government's lien search letter and how to order it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    offered: Offered = Offered.UNKNOWN
    issuer: str | None = None
    channel: LienOrderChannel = LienOrderChannel.NONE_FOUND
    request_url: str | None = None
    #: The address the government says to send requests to, for an email channel.
    request_email: str | None = None
    #: The company whose portal takes the orders, when it isn't the government's own.
    vendor: str | None = None
    fee_text: str | None = None
    fee_per_parcel: Decimal | None = Field(default=None, ge=0)
    turnaround: str | None = None
    rush: str | None = None
    covers: list[LienCoverage] = Field(default_factory=list)
    excludes: str | None = None
    source_url: str | None = None


class PermitSearch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    url: str | None = None
    platform: PermitPlatform = PermitPlatform.UNKNOWN
    #: The software as its pages brand it.
    platform_name: str | None = None
    search_by: list[str] = Field(default_factory=list)
    status_visible: Offered = Offered.UNKNOWN
    login_required: bool | None = None
    notes: str | None = None


class CodeCaseSearch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    public_search: Offered = Offered.UNKNOWN
    url: str | None = None
    platform_name: str | None = None
    notes: str | None = None


class UtilityProviders(BaseModel):
    """Who provides water, sewer, solid waste and stormwater, and how a balance is asked for."""

    model_config = ConfigDict(str_strip_whitespace=True)

    water_sewer: str | None = None
    solid_waste: str | None = None
    stormwater: str | None = None
    billing_portal: str | None = None
    balance_request: BalanceRequest = BalanceRequest.UNKNOWN
    balance_request_url: str | None = None
    notes: str | None = None


class SpecialAssessments(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    billing: AssessmentBilling = AssessmentBilling.NONE_FOUND
    office: str | None = None
    source_url: str | None = None


class MunicipalOffice(BaseModel):
    """One government's lien, permit, code and utility offices.

    A county's entry is for the county's own offices: the unincorporated area,
    and whatever the county runs countywide. A city's entry is for the city's.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    kind: GovernmentKind
    state: str = Field(min_length=2, max_length=2)
    county: str
    #: The Census Bureau's code for the county or place.
    fips: str | None = None
    website: str | None = None
    lien_letter: LienLetter = Field(default_factory=LienLetter)
    permits: PermitSearch = Field(default_factory=PermitSearch)
    code_enforcement: CodeCaseSearch = Field(default_factory=CodeCaseSearch)
    utilities: UtilityProviders = Field(default_factory=UtilityProviders)
    special_assessments: SpecialAssessments = Field(default_factory=SpecialAssessments)
    notes: str | None = None
    confidence: Confidence = Confidence.LOW
    #: The day the government's pages were read.
    checked_on: date


class MunicipalDirectorySource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    source_name: str | None = None
    #: The day the oldest entry in the answer was read.
    checked_on: date | None = None


class MunicipalLienDirectoryRecord(BaseModel):
    """The offices to ask about a parcel's municipal liens, permits and code cases."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.municipal_lien_directory"
    schema_version: str = "1.0"
    record_type: Literal["municipal_lien_directory"] = "municipal_lien_directory"
    source: MunicipalDirectorySource
    jurisdiction: Jurisdiction
    #: The city's own offices, when a municipality was given and is in the directory.
    municipality: MunicipalOffice | None = None
    #: The county's own offices.
    county: MunicipalOffice | None = None
    notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)

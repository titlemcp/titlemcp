"""A parcel's property tax status: what was billed, what's paid, and what's still owed.

Collectors publish this in different shapes. DC publishes one row per parcel
with the current year's installments and a run of prior years. Hennepin keeps
running totals of tax billed and paid. Ohio's auditors list each year's net tax
and the amount paid. These models are the one shape every tax connector maps
into.

An answer here is a reading of the collector's record as of its date, not a
tax certificate. Every result is marked for human review.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.models import Jurisdiction


class TaxStatus(StrEnum):
    #: Nothing is owed on any year or charge shown.
    PAID = "paid"
    #: Something is owed, and none of it is past its due date.
    DUE = "due"
    #: Something is owed after its due date, or on a year before the latest.
    PAST_DUE = "past_due"
    #: The collector has the parcel but shows no balances to judge by.
    UNKNOWN = "unknown"
    PARCEL_NOT_FOUND = "parcel_not_found"


class TaxInstallment(BaseModel):
    """One installment of a year's tax: a half, a quarter, or a due date."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = None
    due_on: date | None = None
    billed: Decimal | None = None
    paid: Decimal | None = None
    balance: Decimal | None = None


class TaxYear(BaseModel):
    """One tax year's bill, as the collector shows it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tax_year: int = Field(ge=1900, le=2200)
    billed: Decimal | None = None
    paid: Decimal | None = None
    #: Penalties, interest and fees, where the collector shows them apart.
    penalties: Decimal | None = None
    balance: Decimal | None = None
    installments: list[TaxInstallment] = Field(default_factory=list)
    #: The collector's own flags; None where it doesn't say.
    delinquent: bool | None = None
    tax_sale: bool | None = None
    notes: list[str] = Field(default_factory=list)


class TaxCharge(BaseModel):
    """A charge billed with the tax but apart from it, such as a special assessment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str
    billed: Decimal | None = None
    paid: Decimal | None = None
    balance: Decimal | None = None


class PropertyTaxQuery(BaseModel):
    """The parcel to read, by the collector's own parcel or account number."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str = Field(min_length=1)


class TaxParcel(BaseModel):
    """What a tax connector read for one parcel, before it is judged."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parcel_id: str
    taxpayer_name: str | None = None
    property_address: str | None = None
    collector: str | None = None
    #: Newest first.
    years: list[TaxYear] = Field(default_factory=list)
    other_charges: list[TaxCharge] = Field(default_factory=list)
    #: When the collector's data was extracted, where it says.
    data_as_of: date | None = None
    #: What the collector's record says that the amounts don't, such as a lien.
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class TaxSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    source_name: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    data_as_of: date | None = None
    #: How often the collector refreshes what it publishes, in its own words.
    refreshed: str | None = None


class PropertyTaxStatusRecord(BaseModel):
    """One parcel's property tax status from the collector's record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.property_tax_status"
    schema_version: str = "1.0"
    record_type: Literal["property_tax_status"] = "property_tax_status"
    source: TaxSource
    jurisdiction: Jurisdiction
    query: PropertyTaxQuery
    status: TaxStatus
    parcel_id: str | None = None
    taxpayer_name: str | None = None
    property_address: str | None = None
    collector: str | None = None
    years: list[TaxYear] = Field(default_factory=list)
    other_charges: list[TaxCharge] = Field(default_factory=list)
    #: Everything still owed across the years and charges shown.
    total_balance: Decimal | None = None
    notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)


def tax_status(parcel: TaxParcel, today: date) -> TaxStatus:
    """Paid, due or past due, judged only from the balances and dates shown."""
    owed_years = [year for year in parcel.years if (year.balance or 0) > 0]
    owed_charges = [charge for charge in parcel.other_charges if (charge.balance or 0) > 0]
    known = [year.balance for year in parcel.years if year.balance is not None] + [
        charge.balance for charge in parcel.other_charges if charge.balance is not None
    ]
    if not known:
        return TaxStatus.UNKNOWN
    if not owed_years and not owed_charges:
        return TaxStatus.PAID
    latest = max(year.tax_year for year in parcel.years) if parcel.years else None
    for year in owed_years:
        if latest is not None and year.tax_year < latest:
            return TaxStatus.PAST_DUE
        if year.delinquent or year.tax_sale:
            return TaxStatus.PAST_DUE
        if any(
            (installment.balance or 0) > 0
            and installment.due_on is not None
            and installment.due_on < today
            for installment in year.installments
        ):
            return TaxStatus.PAST_DUE
    return TaxStatus.DUE


def total_balance(parcel: TaxParcel) -> Decimal | None:
    balances = [year.balance for year in parcel.years if year.balance is not None] + [
        charge.balance for charge in parcel.other_charges if charge.balance is not None
    ]
    return sum(balances, Decimal(0)) if balances else None

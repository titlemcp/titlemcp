"""The Shelby County Trustee's bills for a parcel as its tax status."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from title_mcp.domain.tax import TaxInstallment, TaxParcel, TaxYear

COLLECTOR = "Shelby County Trustee"

COUNTY_TAX_NOTE = (
    "These are Shelby County's property tax bills, which the Trustee collects. City "
    "property tax, such as the City of Memphis's, isn't among them; confirm it separately."
)
DUE_DATES_NOTE = (
    "The Trustee says county tax becomes due the first Monday in October and can be paid "
    "through the last day of February without interest. From the delinquency date the "
    "Trustee shows, 1.5% interest is added each month (Tenn. Code Ann. § 67-5-2010). Each "
    "year's date here is the last day before that delinquency date."
)
#: The amounts on a bill that are owed beyond the tax itself.
_CHARGE_FIELDS = ("interest", "totalFees", "court", "atty", "misc")


def tax_parcel(payload: dict[str, Any], *, parcel_id: str = "") -> TaxParcel:
    merged = payload.get("mergedBillData") or []
    balances = {
        str(bill.get("billNumber")): bill.get("billBalances") or {}
        for bill in payload.get("parcelBillData") or []
    }
    unread: list[str] = []
    if payload.get("shelbyCountyBills"):
        unread.append("a group of bills this connector doesn't read")
    if not merged:
        unread.append("bills without amounts")

    rows: dict[int, list[tuple[TaxInstallment, Decimal | None]]] = defaultdict(list)
    for bill in merged:
        number = str(bill.get("billNumber") or "")
        tax_year = _year(bill.get("year"))
        owed = _money(bill.get("totalDue"))
        if owed is None:
            owed = _money(bill.get("unpaidBalance"))
        recorded = balances.get(number, {})
        unpaid = _money(recorded.get("totalUnpaid"))
        if tax_year is None or owed is None:
            unread.append(f"bill {number or 'without a number'} without a year or balance")
            continue
        if unpaid is not None and (unpaid > 0) != (owed > 0):
            unread.append(f"bill {number}, whose balances disagree")
            continue
        delinquent_on = _iso_date(bill.get("delinquentDate"))
        installment = TaxInstallment(
            label=f"bill {number}",
            due_on=delinquent_on - timedelta(days=1) if delinquent_on else None,
            billed=_money(recorded.get("principalBillAmount")),
            paid=_money(recorded.get("totalPaid")),
            balance=owed,
        )
        # The billing system's past-due figures count from the bill date in August,
        # not the delinquency date, so status comes from the delinquency date alone.
        rows[tax_year].append(
            (installment, _sum(_money(bill.get(field)) for field in _CHARGE_FIELDS))
        )

    tax_sale = bool(payload.get("hasTaxSaleCondition"))
    years = [_tax_year(tax_year, bills) for tax_year, bills in rows.items()]
    notes: list[str] = []
    if tax_sale:
        code = _text(payload.get("specialCode"))
        notes.append(
            "The Trustee shows this parcel scheduled for tax sale"
            + (f" (code {code})." if code else ".")
        )
    conditions = _conditions(payload.get("parcelSpecialConditions") or [])
    if conditions:
        notes.append(f"The Trustee's record lists special condition codes: {conditions}.")
    if unread:
        for year in years:
            year.balance = None
            for installment in year.installments:
                installment.balance = None
        notes.append(
            "The Trustee's record shows "
            + "; ".join(unread)
            + ". This connector doesn't read that, so paid or owed is left unknown. "
            "Check the parcel on the Trustee's Tax Query."
        )
    if years:
        notes.extend([COUNTY_TAX_NOTE, DUE_DATES_NOTE])
    latest = max(merged, key=lambda bill: _year(bill.get("year")) or 0) if merged else {}
    return TaxParcel(
        parcel_id=_text(latest.get("parcel")) or parcel_id,
        taxpayer_name=_text(latest.get("primaryName")) or None,
        property_address=_text(latest.get("location")) or None,
        collector=COLLECTOR,
        years=sorted(years, key=lambda year: year.tax_year, reverse=True),
        notes=notes,
        raw=payload,
    )


def _tax_year(tax_year: int, bills: list[tuple[TaxInstallment, Decimal | None]]) -> TaxYear:
    installments = [installment for installment, _ in bills]
    return TaxYear(
        tax_year=tax_year,
        billed=_all_or_none(installment.billed for installment in installments),
        paid=_all_or_none(installment.paid for installment in installments),
        penalties=_sum(penalties for _, penalties in bills),
        balance=_all_or_none(installment.balance for installment in installments),
        installments=installments,
    )


def _conditions(conditions: list[dict[str, Any]]) -> str:
    years: dict[str, list[str]] = defaultdict(list)
    for condition in conditions:
        code = _text(condition.get("specialConditionCode"))
        if code:
            years[code].append(str(condition.get("billYear") or "?"))
    return "; ".join(f"{code} ({', '.join(sorted(set(found)))})" for code, found in years.items())


def _all_or_none(values) -> Decimal | None:
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return sum(values, Decimal(0))


def _sum(values) -> Decimal | None:
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def _money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except ArithmeticError:
        return None


def _year(value: Any) -> int | None:
    text = _text(value)
    return int(text) if text.isdigit() and len(text) == 4 else None


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())

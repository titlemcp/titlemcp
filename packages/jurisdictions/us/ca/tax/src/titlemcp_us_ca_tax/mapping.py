"""Contra Costa APNs, and the county lookup's answer as a parcel's tax status."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from title_mcp.domain.tax import TaxCharge, TaxInstallment, TaxParcel, TaxYear

COLLECTOR = "Contra Costa County Treasurer-Tax Collector"

#: Bill types read here. Unsecured bills belong to accounts, not parcels.
_READ_TYPES = frozenset({"SECURED", "SUPPLEMENTAL", "REDEMPTION"})
#: Installment statuses read here. PARTIAL and anything new leave the parcel unknown.
_READ_STATUSES = frozenset({"PAID", "NOT PAID", "PENDING"})
_ORDINALS = {1: "1st", 2: "2nd"}

DUE_DATES_NOTE = (
    "The county's lookup shows the first installment due November 1 and the second "
    "February 1. Each installment's date here is the last day to pay it before it is "
    "delinquent, as the county gives it."
)
LOOKUP_NOTE = (
    "The county says its lookup may not reflect pending payments or corrections, and a "
    "delinquent amount is what it shows owed on the lookup's date."
)


def apn_digits(parcel_id: str) -> str | None:
    """The APN as the lookup takes it: nine or ten digits, the tenth a check digit."""
    digits = re.sub(r"\D", "", parcel_id)
    return digits if len(digits) in (9, 10) else None


def tax_parcel(payload: dict[str, Any], *, parcel_id: str = "") -> TaxParcel:
    details = payload.get("details") or {}
    installments: dict[int, list[tuple[TaxInstallment, dict[str, Any]]]] = defaultdict(list)
    supplemental: dict[str, list[tuple[TaxInstallment, dict[str, Any], int | None]]] = defaultdict(
        list
    )
    unread: list[str] = []
    notes: list[str] = []
    for item in payload.get("installments") or []:
        kind = _text(item.get("type")).upper()
        status = _text(item.get("status")).upper()
        amount = _money(item.get("amount"))
        tax_year = _tax_year(item, kind)
        if kind not in _READ_TYPES or status not in _READ_STATUSES:
            unread.append(f"{_describe(item)} with status {status or 'blank'}")
            continue
        if amount is None or (tax_year is None and kind != "SUPPLEMENTAL"):
            unread.append(f"{_describe(item)} whose amount or tax year can't be read")
            continue
        installment = _installment(item, kind, status, amount)
        if kind == "SUPPLEMENTAL":
            supplemental[_text(item.get("billNumber"))].append((installment, item, tax_year))
        else:
            installments[tax_year].append((installment, item))
        if status == "PENDING":
            paid_on = _text(item.get("paidDate"))
            notes.append(
                f"A payment{' made ' + paid_on if paid_on else ''} on the {installment.label}"
                f"{' for ' + _fiscal(tax_year) if tax_year else ''} is pending; it is counted "
                "as owed until it clears."
            )

    charges: list[TaxCharge] = []
    for bill, rows in supplemental.items():
        late = [
            tax_year
            for installment, item, tax_year in rows
            if item.get("isDelinquent") and (installment.balance or 0) > 0
        ]
        if late and None in late:
            unread.append(f"a delinquent supplemental bill {bill} whose tax year can't be read")
        elif late:
            # Delinquent, so it joins its year and the year reads as past due.
            for installment, item, tax_year in rows:
                installments[tax_year].append((installment, item))
        else:
            charges.append(_supplemental_charge(bill, rows))
            notes.append(_supplemental_note(bill, rows))

    years = [_year(tax_year, rows) for tax_year, rows in installments.items()]
    if (details.get("delinquent") or details.get("owesPriorYear")) and not any(
        year.delinquent for year in years
    ):
        unread.append("a delinquency flag on the parcel, but no delinquent installment")
    if unread:
        for year in years:
            year.balance = None
            for installment in year.installments:
                installment.balance = None
        for charge in charges:
            charge.balance = None
        notes.append(
            "The lookup shows "
            + "; ".join(unread)
            + ". This connector doesn't read that, so paid or owed is left unknown. "
            "Check the parcel on the county's lookup."
        )
    if details.get("onPaymentPlan"):
        notes.append("The county shows the parcel on a payment plan.")
    notes.extend(_text(_strip_tags(message)) for message in payload.get("resultsMessages") or [])
    if years or charges:
        notes.extend([DUE_DATES_NOTE, LOOKUP_NOTE])
    return TaxParcel(
        parcel_id=_text(details.get("apn")) or parcel_id,
        property_address=_text(details.get("address")) or None,
        collector=COLLECTOR,
        years=sorted(years, key=lambda year: year.tax_year, reverse=True),
        other_charges=charges,
        data_as_of=_iso_date(payload.get("lookupValidCalendarDate")),
        notes=[note for note in notes if note],
        raw=payload,
    )


def _installment(item: dict[str, Any], kind: str, status: str, amount: Decimal) -> TaxInstallment:
    number = item.get("installmentNumber")
    number = number if isinstance(number, int) else 0
    bill = _text(item.get("billNumber"))
    delinquent = bool(item.get("isDelinquent"))
    if kind == "SECURED":
        label = f"{_ORDINALS.get(number, str(number))} installment"
    elif kind == "SUPPLEMENTAL":
        # The lookup numbers a supplemental bill's installments 3 and 4.
        label = f"supplemental bill {bill}, {_ORDINALS.get(number - 2, str(number))} installment"
    else:
        label = f"redemption bill {bill}"
    paid = status == "PAID"
    return TaxInstallment(
        label=label,
        due_on=None if kind == "REDEMPTION" else _us_date(item.get("dateDue")),
        billed=amount if paid or (kind != "REDEMPTION" and not delinquent) else None,
        paid=amount if paid else (Decimal("0.00") if status == "NOT PAID" else None),
        balance=Decimal("0.00") if paid else amount,
    )


def _year(tax_year: int, rows: list[tuple[TaxInstallment, dict[str, Any]]]) -> TaxYear:
    owed = [
        item
        for installment, item in rows
        if (installment.balance or 0) > 0
        and (item.get("isDelinquent") or _text(item.get("type")).upper() == "REDEMPTION")
    ]
    installments = sorted(
        (installment for installment, _ in rows),
        key=lambda installment: (installment.due_on or date.max, installment.label or ""),
    )
    return TaxYear(
        tax_year=tax_year,
        billed=_all_or_none(installment.billed for installment in installments),
        paid=_all_or_none(installment.paid for installment in installments),
        penalties=_sum(_money(item.get("priorYearDelinquentPenalty")) for _, item in rows),
        balance=_all_or_none(installment.balance for installment in installments),
        installments=installments,
        delinquent=bool(owed),
    )


def _supplemental_charge(
    bill: str, rows: list[tuple[TaxInstallment, dict[str, Any], int | None]]
) -> TaxCharge:
    tax_year = rows[0][2]
    return TaxCharge(
        label=f"Supplemental bill {bill}" + (f" for {_fiscal(tax_year)}" if tax_year else ""),
        billed=_all_or_none(installment.billed for installment, _, _ in rows),
        paid=_all_or_none(installment.paid for installment, _, _ in rows),
        balance=_all_or_none(installment.balance for installment, _, _ in rows),
    )


def _supplemental_note(
    bill: str, rows: list[tuple[TaxInstallment, dict[str, Any], int | None]]
) -> str:
    parts = []
    for installment, _, _ in rows:
        amount = installment.billed if installment.billed is not None else installment.balance
        due = installment.due_on
        if installment.balance == 0:
            state = "paid"
        elif due is not None:
            state = f"delinquent after {due:%B} {due.day}, {due.year}"
        else:
            state = "owed"
        parts.append(f"{installment.label.split(', ')[-1]} ${amount:,} {state}")
    return f"Supplemental bill {bill}: " + "; ".join(parts) + "."


def _fiscal(tax_year: int) -> str:
    return f"{tax_year}-{(tax_year + 1) % 100:02d}"


def _tax_year(item: dict[str, Any], kind: str) -> int | None:
    """The year a bill's tax is for: 2025 for the 2025-26 fiscal year."""
    if kind == "SECURED":
        due = _us_date(item.get("dateDue"))
        number = item.get("installmentNumber")
        if due is not None and number in (1, 2):
            # Delinquent after December 10 of the tax year, then April 10 of the next.
            return due.year if number == 1 else due.year - 1
    code = _text(item.get("priorYearTaxYear")) or _text(item.get("billNumber")).split("-")[0]
    if len(code) == 4 and code.isdigit() and int(code[2:]) == (int(code[:2]) + 1) % 100:
        return 2000 + int(code[:2])
    return None


def _describe(item: dict[str, Any]) -> str:
    kind = _text(item.get("type")).lower() or "untyped"
    bill = _text(item.get("billNumber"))
    return f"a {kind} bill{' ' + bill if bill else ''}"


def _all_or_none(values) -> Decimal | None:
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return sum(values, Decimal(0))


def _sum(values) -> Decimal | None:
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def _money(value: Any) -> Decimal | None:
    text = _text(value).replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except ArithmeticError:
        return None


def _us_date(value: Any) -> date | None:
    try:
        return datetime.strptime(_text(value), "%m/%d/%Y").date()
    except ValueError:
        return None


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError:
        return None


def _strip_tags(value: Any) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())

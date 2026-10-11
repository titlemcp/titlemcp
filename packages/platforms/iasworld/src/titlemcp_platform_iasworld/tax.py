"""A parcel's tax status, read from the auditor's tax tables."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from title_mcp.domain.auditor import PropertyAssessmentRecord
from title_mcp.domain.tax import TaxInstallment, TaxParcel, TaxYear


def taxed_record(records: list[PropertyAssessmentRecord]) -> PropertyAssessmentRecord | None:
    """The record read from the parcel's page, which carries its tax table.

    A search hit and the parcel's page can describe the same parcel in two
    records when their parcel numbers are written differently.
    """
    return next((record for record in records if record.taxes.annual), None) or (
        records[0] if records else None
    )


def tax_parcel_from_assessment(
    record: PropertyAssessmentRecord,
    *,
    read_on: date,
    tax_summary: list[list[str]] | None = None,
) -> TaxParcel:
    """Each year's tax and payments, and the auditor's delinquency flags.

    Every layout lists a year's net tax and total paid. Some also give a Tax
    Summary by half, which becomes the year's installments. Neither shows due
    dates, so a balance on the latest year is owed but not known to be past due.
    """
    by_year: dict[int, TaxYear] = {}
    for annual in record.taxes.annual:
        if not (annual.tax_year or "").isdigit():
            continue
        billed = annual.net_annual_tax.value if annual.net_annual_tax else None
        paid = annual.total_paid.value if annual.total_paid else None
        by_year[int(annual.tax_year)] = TaxYear(
            tax_year=int(annual.tax_year), billed=billed, paid=paid, balance=_owed(billed, paid)
        )
    for year in _summary_years(tax_summary or []):
        by_year[year.tax_year] = year
    years = sorted(by_year.values(), key=lambda year: year.tax_year, reverse=True)

    notes: list[str] = []
    status = record.tax_status
    if status.cdq:
        notes.append("The auditor marks the parcel certified delinquent (CDQ).")
        years = [
            year.model_copy(update={"delinquent": True}) if (year.balance or 0) > 0 else year
            for year in years
        ]
    if status.tax_lien:
        notes.append("The auditor shows a tax lien on the parcel.")
    currently_due = _currently_due(tax_summary or [])
    if currently_due is not None:
        notes.append(f"The auditor's Tax Summary shows ${currently_due:,} currently due.")
    notes.append(
        "The auditor's site shows tax and payments but not due dates; the treasurer has those."
    )
    return TaxParcel(
        parcel_id=record.parcel.parcel_id or "",
        taxpayer_name=record.ownership.owners[0] if record.ownership.owners else None,
        property_address=record.property.site_address_display,
        years=years,
        data_as_of=read_on,
        notes=notes,
        raw={
            "annual_taxes": record.taxes.raw,
            "tax_summary": tax_summary or [],
            "tax_status": status.raw,
        },
    )


def _summary_years(rows: list[list[str]]) -> list[TaxYear]:
    """Years from a Tax Summary laid out as Year, Prior Year, 1st Half, 2nd Half, with payments.

    "Prior Year" is what is still owed from earlier years, so it becomes the
    year before, noted as possibly spanning several.
    """
    if len(rows) < 2:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    if "year" not in header or "1st half" not in header:
        return []
    years: list[TaxYear] = []
    for row in rows[1:]:
        cells = dict(zip(header, row, strict=False))
        if not str(cells.get("year", "")).strip().isdigit():
            continue
        tax_year = int(cells["year"])
        installments = [
            TaxInstallment(
                label=label,
                billed=_money(cells.get(name)),
                paid=_money(cells.get(f"{name} payments")),
                balance=_owed(_money(cells.get(name)), _money(cells.get(f"{name} payments"))),
            )
            for name, label in (("1st half", "1st half"), ("2nd half", "2nd half"))
            if name in cells
        ]
        years.append(
            TaxYear(
                tax_year=tax_year,
                billed=_total(installment.billed for installment in installments),
                paid=_total(installment.paid for installment in installments),
                balance=_total(installment.balance for installment in installments),
                installments=installments,
            )
        )
        prior, prior_paid = (
            _money(cells.get("prior year")),
            _money(cells.get("prior year payments")),
        )
        if prior:
            years.append(
                TaxYear(
                    tax_year=tax_year - 1,
                    billed=prior,
                    paid=prior_paid,
                    balance=_owed(prior, prior_paid),
                    notes=["The auditor's Prior Year amount, which can span several years."],
                )
            )
    return years


def _currently_due(rows: list[list[str]]) -> Decimal | None:
    """The Tax Summary's own "Total Currently Due" for its latest year."""
    if len(rows) < 2:
        return None
    header = [cell.strip().lower() for cell in rows[0]]
    if "total currently due" not in header:
        return None
    column = header.index("total currently due")
    return _money(rows[1][column]) if len(rows[1]) > column else None


def _owed(billed: Decimal | None, paid: Decimal | None) -> Decimal | None:
    if billed is None or paid is None:
        return None
    return max(billed - paid, Decimal(0))


def _total(values) -> Decimal | None:
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def _money(value: Any) -> Decimal | None:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None

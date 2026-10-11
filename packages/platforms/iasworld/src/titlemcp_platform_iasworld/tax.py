"""A parcel's tax status, read from the auditor's tax tables."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from title_mcp.domain.auditor import PropertyAssessmentRecord
from title_mcp.domain.tax import TaxInstallment, TaxParcel, TaxYear
from titlemcp_platform_iasworld.config import IasWorldSiteConfig, TaxPage
from titlemcp_platform_iasworld.models import IasWorldTaxPages

# The datalet tabs each layout reads, beyond the parcel's own page.
TAX_TABS: dict[TaxPage, tuple[str, ...]] = {
    TaxPage.AUDITOR: (),
    TaxPage.CURRENT_YEAR_SUMMARY: ("tax_details",),
    TaxPage.BILLED_AND_PAYMENTS: ("tax_all", "tax_collection", "redemption", "tax_status"),
    TaxPage.BALANCE_DUE: ("tax_hist",),
    TaxPage.COUNTY_RECEIVABLE: (),
}


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


def tax_parcel_from_pages(
    config: IasWorldSiteConfig, pages: IasWorldTaxPages, *, read_on: date
) -> TaxParcel:
    """A parcel's tax from a county's tax tabs, read as ``config.tax_page`` lays them out."""
    years, notes = _READERS[config.tax_page](config, pages)
    hit, page = pages.hit, pages.parcel_page
    parcel_id = (page.site_pin if page else None) or (hit.parcel_id if hit else None) or ""
    return TaxParcel(
        parcel_id=re.sub(r"\s+", " ", parcel_id).strip(),
        taxpayer_name=(hit.owner if hit else None) or (page.owner_display if page else None),
        property_address=(hit.address if hit else None) or (page.site_address if page else None),
        collector=config.owner,
        years=sorted(years, key=lambda year: year.tax_year, reverse=True),
        data_as_of=pages.last_updated or read_on,
        notes=[*config.tax_notes, *notes],
        raw={
            "tables": {
                title: rows
                for detail in [*pages.tabs.values(), page]
                if detail
                for title, rows in detail.raw_section_rows.items()
                if not _CHROME.match(title)
            }
        },
    )


def _current_year_summary(
    config: IasWorldSiteConfig, pages: IasWorldTaxPages
) -> tuple[list[TaxYear], list[str]]:
    """Fairfax's Summary of Current Year Taxes: a row per half, then a total.

    Columns run from the year and the half's name, through each charge and any
    interest and penalty, to Amount Paid (written negative) and Balance Due.
    """
    title = "Summary of Current Year Taxes"
    rows = pages.section(title) or []
    header = _header(rows)
    paid_at, balance_at = _column(header, "amount paid"), _column(header, "balance due")
    if paid_at is None or balance_at is None:
        return [], [_UNREAD_TABLE.format(title=title)]
    charge_at = [i for i in range(2, paid_at) if not _PENALTY.search(header[i])]
    penalty_at = [i for i in range(2, paid_at) if _PENALTY.search(header[i])]
    halves: dict[int, list[tuple[TaxInstallment, Decimal | None]]] = {}
    for row in rows[1:]:
        tax_year = _year(_cell(row, 0))
        if tax_year is None or len(row) <= balance_at:
            continue
        earlier = halves.setdefault(tax_year, [])
        installment = TaxInstallment(
            label=_installment_label(_cell(row, 1), len(earlier)),
            due_on=_due_on(config, tax_year, len(earlier)),
            billed=_total(_money(row[i]) for i in charge_at),
            paid=_positive(_money(row[paid_at])),
            balance=_money(row[balance_at]),
        )
        earlier.append((installment, _total(_money(row[i]) for i in penalty_at)))
    years = [
        _year_of(
            tax_year,
            [installment for installment, _ in items],
            penalties=_total(penalties for _, penalties in items),
        )
        for tax_year, items in halves.items()
    ]
    notes = []
    for label, value in _labelled(pages.section("Prepays and Refunds")):
        amount = _money(value)
        if amount and label.lower() in ("prepays", "pending refunds"):
            notes.append(f"The county shows {label.lower()} of ${amount:,}.")
    return years, notes


def _billed_and_payments(
    config: IasWorldSiteConfig, pages: IasWorldTaxPages
) -> tuple[list[TaxYear], list[str]]:
    """DuPage: the tax billed for the year, less the tax in each payment for that year.

    The page doesn't show installment amounts, so with due dates configured each
    installment is taken as an equal share of the bill, paid in order.
    """
    billed: dict[int, Decimal] = {}
    for row in (pages.section("Taxes Billed") or [])[1:]:
        tax_year, amount = _year(_cell(row, 0)), _money(_cell(row, 1))
        if tax_year is not None and amount is not None:
            billed[tax_year] = amount
    if not billed:
        return [], ["The county's page showed no tax billed."]
    payments = pages.section("Payment Details") or []
    header = _header(payments)
    year_at, tax_at = _column(header, "year"), _column(header, "tax")
    extra_at = [_column(header, name) for name in ("interest", "penalty", "cost")]
    paid: dict[int, Decimal] = {}
    penalties: dict[int, Decimal] = {}
    if year_at is not None and tax_at is not None:
        for row in payments[1:]:
            tax_year = _year(_cell(row, year_at))
            if tax_year is None:
                continue
            paid[tax_year] = paid.get(tax_year, Decimal(0)) + (_money(_cell(row, tax_at)) or 0)
            extra = _total(_money(_cell(row, at)) for at in extra_at if at is not None)
            penalties[tax_year] = penalties.get(tax_year, Decimal(0)) + (extra or 0)
    years = []
    for tax_year, amount in billed.items():
        year_paid = paid.get(tax_year, Decimal("0.00"))
        years.append(
            TaxYear(
                tax_year=tax_year,
                billed=amount,
                paid=year_paid,
                penalties=penalties.get(tax_year) or None,
                balance=max(amount - year_paid, Decimal("0.00")),
                installments=_equal_shares(config, tax_year, amount, year_paid),
            )
        )
    notes = []
    if config.tax_due_dates:
        notes.append(
            "The county's page doesn't list installment amounts, so each is taken as an "
            "equal share of the year's tax."
        )
    for mode, flag, found in (
        ("redemption", "tax_sale", "The county lists taxes sold at tax sale and not yet redeemed."),
        ("tax_status", "delinquent", "The county's Tax Status page has an entry for the parcel."),
    ):
        years, more = _apply_listing(
            years, _tab_sections(pages, mode), flag=flag, found=found, read=mode == "redemption"
        )
        notes += more
    return years, notes


def _balance_due(
    config: IasWorldSiteConfig, pages: IasWorldTaxPages
) -> tuple[list[TaxYear], list[str]]:
    """Bernalillo: each year's tax, interest, penalty, fees, payments and amount due.

    Current Amount Due breaks the latest year into its halves.
    """
    title = "Payment History"
    history = pages.section(title) or []
    header = _header(history)
    year_at = _column(header, "prior yr", "tax year", "year")
    at = {name: _column(header, name) for name in ("tax", "int", "pen", "fees", "paid", "due")}
    if year_at is None or at["tax"] is None or at["due"] is None:
        return [], [_UNREAD_TABLE.format(title=title)]
    years: dict[int, TaxYear] = {}
    for row in history[1:]:
        tax_year = _year(_cell(row, year_at))
        if tax_year is None:
            continue
        years[tax_year] = TaxYear(
            tax_year=tax_year,
            billed=_money(_cell(row, at["tax"])),
            paid=_positive(_money(_cell(row, at["paid"]))),
            penalties=_total(_money(_cell(row, at[name])) for name in ("int", "pen", "fees")),
            balance=_money(_cell(row, at["due"])),
        )

    current_rows = pages.section("Current Amount Due") or []
    current_at = {name: _column(_header(current_rows), name) for name in at}
    tab = pages.tabs.get("tax_hist")
    current_year = _year(tab.tax_year if tab else None) or (max(years) if years else None)
    installments: list[TaxInstallment] = []
    if current_year is not None and current_at["due"] is not None:
        for row in current_rows[1:]:
            label = _cell(row, 0).strip()
            if not label or label.lower().startswith("total"):
                continue
            installments.append(
                TaxInstallment(
                    label=_installment_label(label, len(installments)),
                    due_on=_due_on(config, current_year, len(installments)),
                    billed=_money(_cell(row, current_at["tax"])),
                    paid=_positive(_money(_cell(row, current_at["paid"]))),
                    balance=_money(_cell(row, current_at["due"])),
                )
            )
    if installments:
        year = years.get(current_year) or _year_of(current_year, installments)
        years[current_year] = year.model_copy(update={"installments": installments})

    notes = []
    pending = dict(_labelled(pages.section("Pending Payment Balance")))
    total_due = _money(pending.get("Total Due"))
    good_through = pending.get("Total due valid until")
    if total_due and good_through:
        notes.append(f"The county quotes ${total_due:,} due, good through {good_through}.")
    return list(years.values()), notes


def _county_receivable(
    config: IasWorldSiteConfig, pages: IasWorldTaxPages
) -> tuple[list[TaxYear], list[str]]:
    """Delaware County, PA: each county bill's face amount, discount, penalty and payment.

    A bill paid early carries a discount, so what was paid can be less than the
    bill with nothing owed. Delinquent Tax lists what has gone to the tax claim
    bureau.
    """
    title = "County Tax Receivable"
    rows = pages.section(title) or []
    header = _header(rows)
    year_at, face_at = _column(header, "tax year"), _column(header, "face amount due")
    balance_at = _column(header, "balance")
    if year_at is None or face_at is None or balance_at is None:
        return [], [_UNREAD_TABLE.format(title=title)]
    at = {
        name: _column(header, name)
        for name in (
            "billing period",
            "billing date",
            "discount posted",
            "penalty posted",
            "fees posted",
            "payment posted",
        )
    }
    bills: dict[int, list[tuple[TaxInstallment, Decimal | None, Decimal | None]]] = {}
    for row in rows[1:]:
        tax_year = _year(_cell(row, year_at))
        if tax_year is None:
            continue
        earlier = bills.setdefault(tax_year, [])
        period = _cell(row, at["billing period"]).strip()
        due_on = _months_after(
            _us_date(_cell(row, at["billing date"])), config.tax_due_months_after_billing
        )
        bill = TaxInstallment(
            label=f"County tax, {period.lower()} bill" if period else "County tax",
            due_on=due_on or _due_on(config, tax_year, len(earlier)),
            billed=_money(_cell(row, face_at)),
            paid=_positive(_money(_cell(row, at["payment posted"]))),
            balance=_money(_cell(row, balance_at)),
        )
        penalties = _total(
            _money(_cell(row, at[name])) for name in ("penalty posted", "fees posted")
        )
        earlier.append((bill, penalties, _positive(_money(_cell(row, at["discount posted"])))))
    years = []
    for tax_year, items in bills.items():
        discount = _total(discount for _, _, discount in items)
        years.append(
            _year_of(
                tax_year,
                [bill for bill, _, _ in items],
                penalties=_total(penalties for _, penalties, _ in items),
                notes=[f"Paid with a ${discount:,} discount."] if discount else [],
            )
        )
    years, notes = _apply_listing(
        years,
        {"Delinquent Tax": pages.section("Delinquent Tax") or []},
        flag="delinquent",
        found="The county lists delinquent county tax for the parcel.",
        read=True,
    )
    return years, notes


_READERS = {
    TaxPage.CURRENT_YEAR_SUMMARY: _current_year_summary,
    TaxPage.BILLED_AND_PAYMENTS: _billed_and_payments,
    TaxPage.BALANCE_DUE: _balance_due,
    TaxPage.COUNTY_RECEIVABLE: _county_receivable,
}

# Layout tables iasWorld numbers rather than names: reports menus, copyright lines.
_CHROME = re.compile(r"^Table\d*$", re.IGNORECASE)
_PENALTY = re.compile(r"interest|penalty", re.IGNORECASE)
_NOTHING_LISTED = re.compile(r"no outstanding|no data|none found", re.IGNORECASE)
_UNREAD_TABLE = "The county's {title} table wasn't laid out as expected, so it wasn't read."


def _apply_listing(
    years: list[TaxYear],
    sections: dict[str, list[list[str]]],
    *,
    flag: str,
    found: str,
    read: bool,
) -> tuple[list[TaxYear], list[str]]:
    """Marks the years a delinquent or sold-tax table lists, with what it says is owed.

    A table that lists something it can't be read from leaves every balance
    unknown, so the answer can't say paid while the county shows tax owed.
    """
    listed = {
        title: rows
        for title, rows in sections.items()
        if rows and not _NOTHING_LISTED.search(" ".join(" ".join(row) for row in rows))
    }
    if not listed:
        return years, []
    amounts = [_listed_years(rows) if read else None for rows in listed.values()]
    if any(entries is None for entries in amounts):
        unknown = [
            year.model_copy(
                update={
                    "balance": None,
                    "installments": [
                        installment.model_copy(update={"balance": None})
                        for installment in year.installments
                    ],
                }
            )
            for year in years
        ]
        titles = ", ".join(listed)
        return unknown, [
            f"{found} The {titles} table couldn't be read, so balances are left unknown; "
            "check the county's page."
        ]
    by_year = {year.tax_year: year for year in years}
    for entries in amounts:
        for tax_year, amount in entries or []:
            year = by_year.get(tax_year) or TaxYear(tax_year=tax_year)
            by_year[tax_year] = year.model_copy(update={flag: True, "balance": amount})
    return list(by_year.values()), [found]


def _listed_years(rows: list[list[str]]) -> list[tuple[int, Decimal]] | None:
    """Each listed year and its amount, from a table with a year and an amount column."""
    header = _header(rows)
    year_at = _column(header, "tax year", "year", "levy year", "prior yr")
    amount_at = next(
        (
            index
            for word in ("balance", "total due", "amount due", "due", "total", "amount")
            for index, name in enumerate(header)
            if word in name
        ),
        None,
    )
    if year_at is None or amount_at is None:
        return None
    entries = []
    for row in rows[1:]:
        tax_year = _year(_cell(row, year_at))
        if tax_year is None:
            continue
        amount = _money(_cell(row, amount_at))
        if amount is None:
            return None
        entries.append((tax_year, amount))
    return entries or None


def _tab_sections(pages: IasWorldTaxPages, mode: str) -> dict[str, list[list[str]]]:
    tab = pages.tabs.get(mode)
    if tab is None:
        return {}
    return {title: rows for title, rows in tab.raw_section_rows.items() if not _CHROME.match(title)}


def _equal_shares(
    config: IasWorldSiteConfig, tax_year: int, billed: Decimal, paid: Decimal
) -> list[TaxInstallment]:
    dates = config.tax_due_dates
    if not dates:
        return []
    share = (billed / len(dates)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    shares = [share] * (len(dates) - 1) + [billed - share * (len(dates) - 1)]
    installments = []
    for due, amount in zip(dates, shares, strict=True):
        applied = min(paid, amount)
        paid -= applied
        installments.append(
            TaxInstallment(
                label=due.label,
                due_on=due.on(tax_year),
                billed=amount,
                paid=applied,
                balance=amount - applied,
            )
        )
    return installments


def _year_of(
    tax_year: int,
    installments: list[TaxInstallment],
    *,
    penalties: Decimal | None = None,
    notes: list[str] | None = None,
) -> TaxYear:
    return TaxYear(
        tax_year=tax_year,
        billed=_total(installment.billed for installment in installments),
        paid=_total(installment.paid for installment in installments),
        penalties=penalties,
        balance=_total(installment.balance for installment in installments),
        installments=installments,
        notes=notes or [],
    )


def _due_on(config: IasWorldSiteConfig, tax_year: int, index: int) -> date | None:
    dates = config.tax_due_dates
    return dates[index].on(tax_year) if index < len(dates) else None


def _months_after(start: date | None, months: int | None) -> date | None:
    if start is None or not months:
        return None
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    for day in (start.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _us_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _installment_label(text: str, index: int) -> str:
    label = re.sub(r"\s+due$", "", text.strip(), flags=re.IGNORECASE).lower()
    return label or f"installment {index + 1}"


def _header(rows: list[list[str]]) -> list[str]:
    return [re.sub(r"[:\s]+$", "", cell.strip()).lower() for cell in rows[0]] if rows else []


def _column(header: list[str], *names: str) -> int | None:
    return next((header.index(name) for name in names if name in header), None)


def _cell(row: list[str], at: int | None) -> str:
    return row[at] if at is not None and at < len(row) else ""


def _labelled(rows: list[list[str]] | None):
    for row in rows or []:
        if len(row) >= 2:
            yield row[0].strip().rstrip(":").strip(), row[1]


def _year(value: str | None) -> int | None:
    text = str(value or "").strip()
    return int(text) if re.fullmatch(r"(19|20|21)\d\d", text) else None


def _positive(value: Decimal | None) -> Decimal | None:
    return abs(value) if value is not None else None

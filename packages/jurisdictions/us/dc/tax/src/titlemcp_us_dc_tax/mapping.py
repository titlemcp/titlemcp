"""DC parcel numbers, and an extract row as a parcel's tax status."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from title_mcp.domain.tax import TaxCharge, TaxInstallment, TaxParcel, TaxYear

COLLECTOR = "District of Columbia Office of Tax and Revenue"

#: The two halves of the current year in the extract, and their due dates
#: (D.C. Code § 47-811(b)): March 31 and September 15 of the tax year.
_HALVES = (("CY1", "1st half", 3, 31), ("CY2", "2nd half", 9, 15))
_PRIOR_YEARS = tuple(f"PY{n}" for n in range(1, 11))
#: Charges billed with the tax, by the extract's field prefix.
_CHARGES = (
    ("BID", "Business improvement district"),
    ("PACE", "PACE assessment"),
    ("SEWS", "SEWS assessment"),
    ("SWWSAD", "SWWSAD assessment"),
)

_SQUARE_LOT = re.compile(
    r"^(?:SQUARE\s+|SQ\s+)?(\d{1,4})\s*(?!LOT\b)([A-Z]{0,4})[\s\-/]+(?:LOT\s+)?(\d{1,4})$"
)


def ssl_candidates(parcel_id: str) -> list[str]:
    """The parcel's SSL as the extract stores it, from the ways people write it.

    The extract keeps square, suffix and lot in four columns each, padded:
    square 4559, lot 63 is ``4559    0063``. Other parcel kinds (``PAR``,
    ``PI``) are matched as given.
    """
    as_given = parcel_id.strip().upper()
    candidates = [as_given]
    match = _SQUARE_LOT.match(" ".join(as_given.split()))
    if match:
        square, suffix, lot = match.groups()
        candidates.insert(0, f"{square.zfill(4)}{suffix.ljust(4)}{lot.zfill(4)}")
    return list(dict.fromkeys(candidates))


def tax_parcel(row: dict[str, Any], *, data_as_of: date | None) -> TaxParcel:
    years: list[TaxYear] = []
    current = _current_year(row)
    if current is not None:
        years.append(current)
    for prefix in _PRIOR_YEARS:
        tax_year = _year(row.get(f"{prefix}YEAR"))
        if tax_year is None or (current is not None and tax_year == current.tax_year):
            continue
        years.append(
            TaxYear(
                tax_year=tax_year,
                billed=_money(row.get(f"{prefix}TAX")),
                paid=_money(row.get(f"{prefix}COLL")),
                penalties=_penalties(row, prefix),
                balance=_money(row.get(f"{prefix}BAL")),
                tax_sale=_flag(row.get(f"{prefix}TXSALE")),
            )
        )
    charges = [
        TaxCharge(
            label=label,
            billed=_money(row.get(f"{prefix}TOTALDUE")),
            paid=_money(row.get(f"{prefix}COLLECTED")),
            balance=_money(row.get(f"{prefix}BALANCE")),
        )
        for prefix, label in _CHARGES
        if any(_money(row.get(f"{prefix}{field}")) for field in ("TOTALDUE", "BALANCE"))
    ]
    notes = []
    if current is not None:
        notes.append(
            "The first half is due March 31 and the second half September 15 "
            "(D.C. Code § 47-811); a bill mailed late is due later."
        )
    return TaxParcel(
        parcel_id=str(row.get("SSL") or "").strip(),
        taxpayer_name=_text(row.get("OWNERNAME")),
        property_address=_text(row.get("PREMISEADD")),
        collector=COLLECTOR,
        years=sorted(years, key=lambda year: year.tax_year, reverse=True),
        other_charges=charges,
        data_as_of=data_as_of,
        notes=notes,
        raw=row,
    )


def _current_year(row: dict[str, Any]) -> TaxYear | None:
    tax_year = _year(row.get("CY1YEAR")) or _year(row.get("CY2YEAR"))
    if tax_year is None:
        return None
    installments = [
        TaxInstallment(
            label=label,
            due_on=date(tax_year, month, day),
            billed=_money(row.get(f"{prefix}TAX")),
            paid=_money(row.get(f"{prefix}COLL")),
            balance=_money(row.get(f"{prefix}BAL")),
        )
        for prefix, label, month, day in _HALVES
        if _year(row.get(f"{prefix}YEAR")) == tax_year
    ]
    return TaxYear(
        tax_year=tax_year,
        billed=_sum(installment.billed for installment in installments),
        paid=_sum(installment.paid for installment in installments),
        penalties=_sum(_penalties(row, prefix) for prefix, *_ in _HALVES),
        balance=_sum(installment.balance for installment in installments),
        installments=installments,
        tax_sale=any(_flag(row.get(f"{prefix}TXSALE")) for prefix, *_ in _HALVES) or None,
    )


def _penalties(row: dict[str, Any], prefix: str) -> Decimal | None:
    return _sum(_money(row.get(f"{prefix}{field}")) for field in ("PEN", "INT", "FEE"))


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
    text = str(value or "").strip()
    return int(text) if text.isdigit() and len(text) == 4 else None


def _flag(value: Any) -> bool | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    return text not in {"N", "NO", "0", "NONE"}


def _text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.commitment import (
    ClauseOrigin,
    ClauseSet,
    ClauseTemplate,
    CommitmentClause,
    CommitmentDraft,
    CommitmentOrder,
    CommitmentSection,
    CommitmentSubClause,
    ScheduleA,
)
from title_mcp.domain.exam import (
    ExamPackage,
    ExamSheetKind,
    ExceptionEntry,
    ExceptionInstrumentKind,
    JudgmentEntry,
    MortgageEntry,
    TaxParcelEntry,
)
from title_mcp.domain.title import RecordingReference
from title_mcp.services.exam import Discrepancy, ReconciliationResult, ReconciliationStatus


class CommitmentRenderStatus(StrEnum):
    RENDERED = "rendered"
    REFUSED = "refused"


class CommitmentRenderResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.commitment_render"
    schema_version: str = "1.0"
    record_type: str = "commitment_render"
    file_number: str
    status: CommitmentRenderStatus
    draft: CommitmentDraft | None = None
    refusal_reason: str | None = None
    blocking_discrepancies: list[Discrepancy] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)


def format_long_date(value: date | None) -> str:
    if value is None:
        return ""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def format_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}"


_SPOUSES = re.compile(r",?\s*\b(?:h/w|w/h)\b\.?", re.IGNORECASE)
_PLUS = re.compile(r"\s*\+\s*")
_BARE_CO = re.compile(r"\bCo$")


def expand_party(value: str) -> str:
    """Spell out an abstractor's shorthand in a party name for the commitment.

    "Alex Q + Jamie Example h/w" becomes "Alex Q and Jamie Example, husband and wife".
    Only notation is expanded; names are never completed or guessed.
    """

    text = _PLUS.sub(" and ", value.strip())
    text = _SPOUSES.sub(", husband and wife", text)
    return _BARE_CO.sub("Co.", text)


# A bare category label numbered by the form: "Easement #3", "Restrictions 2".
_FORM_ROW = re.compile(
    r"^(?P<label>(?:easements?|restrictions?|exceptions?|agreements?|leases?|plats?|"
    r"rights?[- ]of[- ]ways?|items?))\s*#?\s*\d+$",
    re.IGNORECASE,
)
# A numbered row label in front of the real name: "Other Adverse 1 - Memo of Trust".
_NUMBERED_LABEL = re.compile(
    r"^(?:other(?:\s+adverse)?|adverse|exception|item)\s*#?\s*\d+\s*[-–:]\s+(?=\S)",
    re.IGNORECASE,
)


def instrument_name(value: str | None) -> str:
    """An instrument's name as a clause can use it.

    Sheets number their rows ("Easement #3", "Other Adverse 1 - Memo of Trust"); that
    numbering is the form's, not the instrument's, so it is dropped. Numbers that
    belong to the instrument ("Ordinance #444") are kept.
    """

    text = (value or "").strip()
    row = _FORM_ROW.match(text)
    if row:
        return row["label"]
    text = _NUMBERED_LABEL.sub("", text).strip()
    return text or "instrument"


def _blank(value: str | None, label: str) -> str:
    """A value the sheet did not give legibly prints as a bracketed blank.

    The commitment then reads "[PARCEL NUMBER]" where a person must fill in the
    value, never "UNREADABLE" or a sentence with a hole in it.
    """

    legible = _is_party(value) or bool(value and any(c.isdigit() for c in value))
    return value if legible and value else f"[{label}]"


def _money_or_blank(value: Decimal | None) -> str:
    return format_money(value) if value is not None else "[AMOUNT]"


def _is_party(value: str | None) -> bool:
    """False for the placeholders a blank or illegible party line produces."""

    text = (value or "").strip()
    return bool(text) and text.upper() != "UNREADABLE" and re.search(r"[A-Za-z]", text) is not None


class CommitmentRenderService:
    """Turns reconciled abstractor sheets into commitment clauses.

    Two properties make this safe to automate, and both are structural rather than
    prompted:

    * It renders only from summary-sheet entries a human abstractor wrote, plus
      transaction facts the order supplies. Nothing is derived from the underlying
      documents, so the draft cannot acquire a discretionary exception the
      abstractor did not call for.
    * It refuses outright unless reconciliation came back green, so an internally
      inconsistent package cannot produce a commitment at all.

    There are no model calls here. Every clause is either agency boilerplate or a
    template filled from a typed record.
    """

    def render(
        self,
        *,
        package: ExamPackage,
        reconciliation: ReconciliationResult,
        clause_set: ClauseSet,
        order: CommitmentOrder | None = None,
    ) -> CommitmentRenderResult:
        if reconciliation.file_number != package.file_number:
            return CommitmentRenderResult(
                file_number=package.file_number,
                status=CommitmentRenderStatus.REFUSED,
                refusal_reason=(
                    "Reconciliation belongs to file "
                    f"{reconciliation.file_number}, not {package.file_number}."
                ),
            )

        if order is not None and order.file_number != package.file_number:
            return CommitmentRenderResult(
                file_number=package.file_number,
                status=CommitmentRenderStatus.REFUSED,
                refusal_reason=(
                    f"Order belongs to file {order.file_number}, "
                    f"not {package.file_number}."
                ),
            )

        if reconciliation.status is not ReconciliationStatus.GREEN:
            blocking = reconciliation.blocking
            return CommitmentRenderResult(
                file_number=package.file_number,
                status=CommitmentRenderStatus.REFUSED,
                refusal_reason=(
                    f"Reconciliation is {reconciliation.status.value}: "
                    f"{len(blocking)} blocking discrepancy(ies) must be resolved by a "
                    "human before a commitment can be drafted."
                ),
                blocking_discrepancies=blocking,
            )

        draft = CommitmentDraft(
            file_number=package.file_number,
            clause_set_id=clause_set.clause_set_id,
            schedule_a=ScheduleA.from_order(order) if order is not None else None,
            schedule_b1=self._render_b1(package, clause_set, order),
            schedule_b2=self._render_b2(package, clause_set),
            source_specific={
                "advisory_discrepancies": [
                    d.model_dump(mode="json") for d in reconciliation.advisory
                ],
            },
        )
        return CommitmentRenderResult(
            file_number=package.file_number,
            status=CommitmentRenderStatus.RENDERED,
            draft=draft,
        )

    def _render_b1(
        self,
        package: ExamPackage,
        clause_set: ClauseSet,
        order: CommitmentOrder | None = None,
    ) -> list[CommitmentClause]:
        clauses: list[CommitmentClause] = []
        supplied = set(clause_set.form_supplied_clause_ids)
        number = 0

        for template in clause_set.standard_b1:
            number += 1
            clauses.append(
                CommitmentClause(
                    number=number,
                    clause_id=template.clause_id,
                    section=CommitmentSection.SCHEDULE_B_I,
                    text=template.template,
                    origin=ClauseOrigin.STANDARD,
                    form_supplied=template.clause_id in supplied,
                    sub_items=self._order_sub_items(template, clause_set, order),
                )
            )

        for position, entry in enumerate(package.mortgages):
            number += 1
            clauses.append(
                CommitmentClause(
                    number=number,
                    clause_id=clause_set.mortgage_payoff.clause_id,
                    section=CommitmentSection.SCHEDULE_B_I,
                    text=clause_set.mortgage_payoff.template.format(
                        **self._mortgage_context(entry, clause_set)
                    ),
                    origin=ClauseOrigin.ABSTRACTOR_SHEET,
                    section_header=(
                        clause_set.mortgage_payoff_header if position == 0 else None
                    ),
                    source_sheet=ExamSheetKind.MORTGAGES,
                    src_page=entry.provenance.src_page,
                )
            )

        judgment = clause_set.judgment_requirement
        if judgment is not None:
            for position, j in enumerate(package.judgments):
                number += 1
                clauses.append(
                    CommitmentClause(
                        number=number,
                        clause_id=judgment.clause_id,
                        section=CommitmentSection.SCHEDULE_B_I,
                        text=judgment.template.format(**self._judgment_context(j, clause_set)),
                        origin=ClauseOrigin.ABSTRACTOR_SHEET,
                        section_header=clause_set.judgment_header if position == 0 else None,
                        source_sheet=ExamSheetKind.JUDGMENTS,
                        src_page=j.provenance.src_page,
                    )
                )

        return clauses

    def _render_b2(self, package: ExamPackage, clause_set: ClauseSet) -> list[CommitmentClause]:
        clauses: list[CommitmentClause] = []
        supplied = set(clause_set.form_supplied_clause_ids)
        number = 0

        for template in clause_set.standard_b2:
            number += 1
            clauses.append(
                CommitmentClause(
                    number=number,
                    clause_id=template.clause_id,
                    section=CommitmentSection.SCHEDULE_B_II,
                    text=template.template,
                    origin=ClauseOrigin.STANDARD,
                    form_supplied=template.clause_id in supplied,
                )
            )

        for entry in package.tax_parcels:
            number += 1
            clauses.append(
                CommitmentClause(
                    number=number,
                    clause_id=clause_set.tax_exception.clause_id,
                    section=CommitmentSection.SCHEDULE_B_II,
                    text=clause_set.tax_exception.template.format(
                        **self._tax_context(entry, package)
                    ),
                    origin=ClauseOrigin.ABSTRACTOR_SHEET,
                    source_sheet=ExamSheetKind.TAX,
                    src_page=entry.provenance.src_page,
                )
            )

        for entry in package.exceptions:
            number += 1
            template = self._exception_template(entry, clause_set)
            clauses.append(
                CommitmentClause(
                    number=number,
                    clause_id=template.clause_id,
                    section=CommitmentSection.SCHEDULE_B_II,
                    text=template.template.format(**self._exception_context(entry, clause_set)),
                    origin=ClauseOrigin.ABSTRACTOR_SHEET,
                    source_sheet=ExamSheetKind.EXCEPTIONS,
                    src_page=entry.provenance.src_page,
                )
            )

        return clauses

    @staticmethod
    def _order_sub_items(
        template: ClauseTemplate,
        clause_set: ClauseSet,
        order: CommitmentOrder | None,
    ) -> list[CommitmentSubClause]:
        """Deed and new-mortgage requirements, built from order data only."""

        if order is None or template.clause_id != clause_set.conveyance_clause_id:
            return []

        items: list[CommitmentSubClause] = []
        labels = ("a.", "b.", "c.", "d.")

        deed = clause_set.deed_requirement
        if deed is not None and order.sellers and order.buyers:
            items.append(
                CommitmentSubClause(
                    label=labels[len(items)],
                    clause_id=deed.clause_id,
                    text=deed.template.format(sellers=order.sellers, buyers=order.buyers),
                    origin=ClauseOrigin.ORDER_DATA,
                )
            )

        mortgage = clause_set.mortgage_requirement
        if mortgage is not None and order.lender and order.loan_amount is not None:
            items.append(
                CommitmentSubClause(
                    label=labels[len(items)],
                    clause_id=mortgage.clause_id,
                    text=mortgage.template.format(
                        mortgagors=order.mortgagors or order.buyers or "",
                        lender=order.lender,
                        amount=format_money(order.loan_amount),
                    ),
                    origin=ClauseOrigin.ORDER_DATA,
                )
            )
        return items

    @staticmethod
    def _mortgage_context(entry: MortgageEntry, clause_set: ClauseSet) -> dict[str, str]:
        return {
            "borrowers": expand_party(_blank(entry.borrowers, "BORROWER")),
            "lender": expand_party(_blank(entry.lender, "LENDER")),
            "amount": _money_or_blank(entry.original_amount),
            "dated_clause": (
                f", dated {format_long_date(entry.executed_date)}" if entry.executed_date else ""
            ),
            "executed_date": format_long_date(entry.executed_date),
            "book_label": clause_set.book_label,
            "book": entry.recording.book or "",
            "page": entry.recording.page or "",
        }

    # Most specific first: a plat that also grants easements reads as a plat, and
    # an easement agreement reads as an easement.
    _KIND_PRECEDENCE = (
        ExceptionInstrumentKind.PLAT,
        ExceptionInstrumentKind.RESTRICTION,
        ExceptionInstrumentKind.EASEMENT,
        ExceptionInstrumentKind.RIGHT_OF_WAY,
        ExceptionInstrumentKind.LEASE,
        ExceptionInstrumentKind.AGREEMENT,
    )
    _PARTY_KINDS = frozenset(
        {
            ExceptionInstrumentKind.EASEMENT,
            ExceptionInstrumentKind.RIGHT_OF_WAY,
            ExceptionInstrumentKind.LEASE,
            ExceptionInstrumentKind.AGREEMENT,
        }
    )

    @classmethod
    def _exception_template(cls, entry: ExceptionEntry, clause_set: ClauseSet) -> ClauseTemplate:
        ref = entry.recording
        recorded = bool(ref.book or ref.page or ref.instrument_number)
        if not recorded and clause_set.unrecorded_exception is not None:
            return clause_set.unrecorded_exception
        kinds = set(entry.instrument_kinds)
        chosen_kind = next((k for k in cls._KIND_PRECEDENCE if k in kinds), None)
        template = (
            clause_set.exception_by_kind.get(chosen_kind.value) if chosen_kind else None
        ) or clause_set.easement_exception
        # Wording that names the parties is only usable when the sheet gives them.
        needs_parties = chosen_kind is None or chosen_kind in cls._PARTY_KINDS
        if needs_parties and not (_is_party(entry.first_party) and _is_party(entry.second_party)):
            easement = chosen_kind in (
                None,
                ExceptionInstrumentKind.EASEMENT,
                ExceptionInstrumentKind.RIGHT_OF_WAY,
            )
            if (
                easement
                and _is_party(entry.second_party)
                and clause_set.grantee_easement_exception is not None
            ):
                return clause_set.grantee_easement_exception
            if clause_set.instrument_exception is not None:
                return clause_set.instrument_exception
        return template

    @staticmethod
    def _book_label(reference: RecordingReference | None, clause_set: ClauseSet) -> str:
        series = (reference.document_type if reference else None) or ""
        key = re.sub(r"[^A-Z]", "", series.upper())
        return clause_set.book_labels.get(key, clause_set.book_label)

    @classmethod
    def _exception_context(cls, entry: ExceptionEntry, clause_set: ClauseSet) -> dict[str, str]:
        dated = format_long_date(entry.executed_date)
        return {
            "first_party": expand_party(entry.first_party),
            "second_party": expand_party(entry.second_party),
            "executed_date": dated,
            "dated_clause": f", dated {dated}" if dated else "",
            "instrument_name": instrument_name(entry.instrument_name),
            "book_label": cls._book_label(entry.recording, clause_set),
            "book": entry.recording.book or "",
            "page": entry.recording.page or "",
        }

    @classmethod
    def _judgment_context(cls, entry: JudgmentEntry, clause_set: ClauseSet) -> dict[str, str]:
        recording = entry.recording
        recorded = ""
        if recording is not None and (recording.book or recording.page):
            recorded = (
                f", recorded in {cls._book_label(recording, clause_set)} "
                f"{recording.book or ''}, Page {recording.page or ''}"
            )
        return {
            "creditor": expand_party(_blank(entry.creditor, "CREDITOR")),
            "debtor": expand_party(_blank(entry.debtor, "DEBTOR")),
            "court_clause": f", in the {entry.court}" if entry.court else "",
            "case_clause": f", Case No. {entry.case_number}" if entry.case_number else "",
            "amount_clause": (
                f", in the amount of ${format_money(entry.amount)}"
                if entry.amount is not None
                else ""
            ),
            "recording_clause": recorded,
        }

    @staticmethod
    def _tax_context(entry: TaxParcelEntry, package: ExamPackage) -> dict[str, str]:
        special_line = ""
        assessment_due = ""
        if entry.special_assessment_amount is not None:
            status = "paid" if entry.special_assessment_paid else "due and payable"
            special_line = (
                f"\nSpecial Assessment in the amount of "
                f"${format_money(entry.special_assessment_amount)} is {status}.\n"
            )
            assessment_due = (
                ", assessments are due and payable annually beginning on or about February 1"
            )

        return {
            "county": package.cover.county or "",
            "tax_year": str(entry.tax_year),
            "next_tax_year": str(entry.tax_year + 1),
            "taxpayer_name": entry.taxpayer_name or "",
            "taxpayer_clause": (
                f" listed in the name of {entry.taxpayer_name}," if entry.taxpayer_name else ""
            ),
            "first_half_amount": _money_or_blank(entry.first_half_amount),
            "first_half_status": "paid" if entry.first_half_paid else "due and payable",
            "second_half_amount": _money_or_blank(entry.second_half_amount),
            "second_half_status": "paid" if entry.second_half_paid else "due and payable",
            "special_assessment_line": special_line,
            "assessment_due_clause": assessment_due,
            "parcel_id": _blank(entry.parcel_id, "PARCEL NUMBER"),
        }

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.exam import ExamSheetKind
from title_mcp.domain.models import Address


class CommitmentSection(StrEnum):
    SCHEDULE_B_I = "schedule_b_i"
    SCHEDULE_B_II = "schedule_b_ii"


class ClauseOrigin(StrEnum):
    """Why a clause is on the commitment.

    Three origins are permitted. ``STANDARD`` is boilerplate the agency puts on every
    commitment; ``ABSTRACTOR_SHEET`` is a matter a human abstractor wrote onto a summary
    sheet; ``ORDER_DATA`` is a transaction fact supplied by the order itself -- the buyer,
    seller, and lender that make up the deed and new-mortgage requirements.

    There is deliberately no origin for a clause inferred from a source document. That is
    what the findings report is for.
    """

    STANDARD = "standard"
    ABSTRACTOR_SHEET = "abstractor_sheet"
    ORDER_DATA = "order_data"


class ClauseTemplate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    clause_id: str = Field(min_length=1)
    section: CommitmentSection
    template: str = Field(min_length=1)


class ClauseSet(BaseModel):
    """An agency's house wording for one jurisdiction and underwriter."""

    model_config = ConfigDict(str_strip_whitespace=True)

    clause_set_id: str = Field(min_length=1)
    description: str | None = None
    book_label: str = "Official Record"
    mortgage_payoff_header: str = "Satisfaction and Release of the following:"
    standard_b1: list[ClauseTemplate] = Field(default_factory=list)
    standard_b2: list[ClauseTemplate] = Field(default_factory=list)
    mortgage_payoff: ClauseTemplate
    tax_exception: ClauseTemplate
    easement_exception: ClauseTemplate
    exception_by_kind: dict[str, ClauseTemplate] = Field(default_factory=dict)
    """Exception wording per instrument kind (restriction, plat, lease, agreement).

    A kind without an entry falls back to ``easement_exception``.
    """
    instrument_exception: ClauseTemplate | None = None
    """Neutral wording for a recorded instrument whose parties are not legible."""
    judgment_requirement: ClauseTemplate | None = None
    """Requirement to release each judgment on the abstractor's judgment sheet."""
    judgment_header: str | None = None
    book_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "OR": "Official Record",
            "DV": "Deed Volume",
            "DB": "Deed Book",
            "MV": "Mortgage Volume",
            "PB": "Plat Book",
            "PLAT": "Plat Book",
            "PLATBOOK": "Plat Book",
            "LB": "Lease Book",
            "MISC": "Miscellaneous Record",
        }
    )
    """Label for a recording's record series, keyed by its normalized code."""
    deed_requirement: ClauseTemplate | None = None
    mortgage_requirement: ClauseTemplate | None = None
    conveyance_clause_id: str = "b1.conveyance_documents"
    """Clause the deed / new-mortgage sub-items attach beneath."""
    form_supplied_clause_ids: list[str] = Field(default_factory=list)
    """Standard clauses the target commitment form already prints.

    They keep their numbers so a renderer writing into that form lines up; the
    renderer skips their text. Set this per form, not per agency.
    """


class CommitmentSubClause(BaseModel):
    """A lettered sub-item beneath a numbered requirement (``4.a``, ``4.b``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1)
    clause_id: str
    text: str = Field(min_length=1)
    origin: ClauseOrigin


class CommitmentClause(BaseModel):
    """One numbered clause on a rendered commitment, with its origin recorded."""

    model_config = ConfigDict(str_strip_whitespace=True)

    number: int = Field(ge=1)
    clause_id: str
    section: CommitmentSection
    text: str = Field(min_length=1)
    origin: ClauseOrigin
    section_header: str | None = None
    source_sheet: ExamSheetKind | None = None
    src_page: int | None = None
    sub_items: list[CommitmentSubClause] = Field(default_factory=list)
    form_supplied: bool = False
    """True when the target commitment form already prints this clause.

    The clause still occupies its number so downstream numbering matches the form;
    a renderer writing into that form skips its text and keeps its sub-items.
    """


class ProposedPolicy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    policy_form: str = Field(min_length=1)
    proposed_insured: str = Field(min_length=1)
    amount_of_insurance: Decimal | None = None
    estate: str = "Fee Simple"


class CommitmentOrder(BaseModel):
    """Transaction facts the order system supplies, not the title exam.

    These drive Schedule A and the deed / new-mortgage requirements. They are not
    inferred from any document.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    file_number: str = Field(min_length=1)
    commitment_number: str | None = None
    commitment_date: str = Field(min_length=1)
    property_address: Address | None = None
    county: str | None = None
    estate: str = "Fee Simple"
    vested_in: str = Field(min_length=1)
    policies: list[ProposedPolicy] = Field(default_factory=list)
    land_description: str = "See Exhibit A attached hereto and made a part hereof."
    sellers: str | None = None
    buyers: str | None = None
    mortgagors: str | None = None
    """Borrowers on the new mortgage, when they differ from the deed grantees."""
    lender: str | None = None
    loan_amount: Decimal | None = None


class ScheduleA(BaseModel):
    """The published subset of the order that appears on Schedule A."""

    model_config = ConfigDict(str_strip_whitespace=True)

    commitment_date: str
    property_address: Address | None = None
    county: str | None = None
    estate: str = "Fee Simple"
    vested_in: str = ""
    policies: list[ProposedPolicy] = Field(default_factory=list)
    land_description: str = ""

    @classmethod
    def from_order(cls, order: CommitmentOrder) -> ScheduleA:
        return cls(
            commitment_date=order.commitment_date,
            property_address=order.property_address,
            county=order.county,
            estate=order.estate,
            vested_in=order.vested_in,
            policies=list(order.policies),
            land_description=order.land_description,
        )


class CommitmentDraft(BaseModel):
    """Canonical record for a rendered, unsigned commitment draft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.commitment_draft"
    schema_version: str = "1.0"
    record_type: str = "commitment_draft"
    file_number: str = Field(min_length=1)
    clause_set_id: str = Field(min_length=1)
    schedule_a: ScheduleA | None = None
    schedule_b1: list[CommitmentClause] = Field(default_factory=list)
    schedule_b2: list[CommitmentClause] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)

    @property
    def clauses(self) -> list[CommitmentClause]:
        return [*self.schedule_b1, *self.schedule_b2]

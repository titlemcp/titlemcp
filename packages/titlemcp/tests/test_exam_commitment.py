from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from title_mcp.domain.commitment import (
    ClauseOrigin,
    CommitmentOrder,
    ProposedPolicy,
)
from title_mcp.domain.exam import (
    ExamPackage,
    ExamSheetKind,
    ExceptionEntry,
    ExceptionInstrumentKind,
    ExtractionConfidence,
    FieldProvenance,
    IndexSummarySheet,
    JudgmentEntry,
    MortgageEntry,
    SearchCoverSheet,
    TaxParcelEntry,
)
from title_mcp.domain.models import Address
from title_mcp.domain.title import RecordingReference
from title_mcp.services.clause_sets import ohio_default_clause_set
from title_mcp.services.commitment import CommitmentRenderService, CommitmentRenderStatus
from title_mcp.services.exam import (
    DiscrepancyCode,
    DiscrepancySeverity,
    ExamReconciliationService,
    ReconciliationStatus,
)

# The fixture below mirrors the structure of a real Ohio residential exam package
# -- sheet layout, declared counts, cross-references, and clause shapes -- with all
# party names, the property address, parcel numbers, and recording references
# replaced. Real files are never checked in; they run locally.

FILE_NUMBER = "OH-00000-SAMPLE"


def _prov(sheet: ExamSheetKind, page: int, text: str | None = None) -> FieldProvenance:
    return FieldProvenance(
        sheet=sheet,
        src_page=page,
        src_text=text,
        confidence=ExtractionConfidence.HIGH,
    )


def sample_package(**overrides: object) -> ExamPackage:
    cover = SearchCoverSheet(
        order_number=FILE_NUMBER,
        county="Example",
        state="OH",
        auditor_owners="Example, Alex Q & Jamie",
        buyers="Sample, Sam & Robin",
        property_address=Address(
            line1="123 Example Road",
            city="Exampleville",
            state="OH",
            postal_code="00000",
        ),
        search_start_date=date(1921, 1, 1),
        completed_date=date(2026, 9, 1),
        last_shown_owner_transfer=RecordingReference(book="0900", page="100"),
        declared_mortgage_count=1,
        declared_judgment_count=0,
        declared_exception_count=2,
        matters_of_concern=[
            "Example concern: confirm whether a recorded life estate is outstanding."
        ],
        provenance=_prov(ExamSheetKind.SEARCH_COVER, 1),
    )

    mortgages = [
        MortgageEntry(
            recording=RecordingReference(
                book="0311", page="415", recorded_date=date(2010, 1, 22)
            ),
            borrowers="Alex Q. Example and Jamie Example, husband and wife",
            lender="Example Savings Bank",
            original_amount=Decimal("100000.00"),
            executed_date=date(2010, 1, 15),
            maturity_date=date(2040, 2, 1),
            provenance=_prov(ExamSheetKind.MORTGAGES, 15),
        )
    ]

    exceptions = [
        ExceptionEntry(
            instrument_kinds=[
                ExceptionInstrumentKind.EASEMENT,
                ExceptionInstrumentKind.RIGHT_OF_WAY,
            ],
            recording=RecordingReference(book="0931", page="104"),
            first_party="Alex Q. and Jamie Example, h/w",
            second_party="Example Power Company",
            executed_date=date(1999, 3, 3),
            provenance=_prov(ExamSheetKind.EXCEPTIONS, 16),
        ),
        ExceptionEntry(
            instrument_kinds=[
                ExceptionInstrumentKind.EASEMENT,
                ExceptionInstrumentKind.RIGHT_OF_WAY,
                ExceptionInstrumentKind.AGREEMENT,
            ],
            recording=RecordingReference(book="0461", page="212"),
            first_party="Alex Example and Pat Example, h/w",
            second_party="Example Gas Transmission Company",
            executed_date=date(1955, 6, 1),
            provenance=_prov(ExamSheetKind.EXCEPTIONS, 16),
        ),
    ]

    tax_parcels = [
        TaxParcelEntry(
            parcel_id="25-0000.000",
            tax_year=2025,
            taxpayer_name="Example Alex and Jamie",
            first_half_amount=Decimal("100.50"),
            first_half_paid=True,
            second_half_amount=Decimal("99.50"),
            second_half_paid=True,
            provenance=_prov(ExamSheetKind.TAX, 11),
        ),
        TaxParcelEntry(
            parcel_id="25-0000.001",
            tax_year=2025,
            taxpayer_name="Example Alex and Jamie",
            first_half_amount=Decimal("1234.56"),
            first_half_paid=True,
            second_half_amount=Decimal("1200.44"),
            second_half_paid=True,
            special_assessment_amount=Decimal("18.00"),
            special_assessment_paid=True,
            special_assessment_label="SOLID WASTE",
            cauv=True,
            provenance=_prov(ExamSheetKind.TAX, 13),
        ),
    ]

    index = IndexSummarySheet(
        mortgages=[RecordingReference(book="0311", page="415")],
        easements_rights_of_way=[
            RecordingReference(book="0461", page="212"),
            RecordingReference(book="0931", page="104"),
        ],
        name_searches=["Example Alex and Jamie", "Sample Sam and Robin"],
        provenance=_prov(ExamSheetKind.INDEX_SUMMARY, 19),
    )

    payload: dict[str, object] = {
        "file_number": FILE_NUMBER,
        "cover": cover,
        "mortgages": mortgages,
        "exceptions": exceptions,
        "judgments": [],
        "tax_parcels": tax_parcels,
        "index": index,
    }
    payload.update(overrides)
    return ExamPackage(**payload)  # type: ignore[arg-type]


def sample_order(**overrides: object) -> CommitmentOrder:
    payload: dict[str, object] = {
        "file_number": FILE_NUMBER,
        "commitment_number": FILE_NUMBER,
        "commitment_date": "September 1, 2026 at 8:00 A.M.",
        "property_address": Address(
            line1="123 Example Road", city="Exampleville",
            state="OH", postal_code="00000",
        ),
        "county": "Example",
        "vested_in": "Alex Q. Example and Jamie Example, husband and wife",
        "policies": [
            ProposedPolicy(
                policy_form="2021 ALTA Owner's Policy",
                proposed_insured="Sam Sample and Robin Sample, husband and wife",
            ),
            ProposedPolicy(
                policy_form="2021 ALTA Loan Policy",
                proposed_insured="Example Federal Credit Union",
                amount_of_insurance=Decimal("80000.00"),
            ),
        ],
        "sellers": "Alex Q. Example and Jamie Example, husband and wife",
        "buyers": "Sam Sample and Robin Sample, husband and wife",
        "lender": "Example Federal Credit Union",
        "loan_amount": Decimal("80000.00"),
    }
    payload.update(overrides)
    return CommitmentOrder(**payload)  # type: ignore[arg-type]


class ExamReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ExamReconciliationService()

    def test_consistent_package_reconciles_green(self) -> None:
        result = self.service.reconcile(sample_package())
        self.assertEqual(result.status, ReconciliationStatus.GREEN)
        self.assertEqual(result.blocking, [])
        self.assertTrue(result.requires_human_review)
        self.assertIn("declared_counts", result.checks_run)
        self.assertIn("index_cross_reference", result.checks_run)

    def test_declared_count_mismatch_blocks(self) -> None:
        package = sample_package()
        package.cover.declared_exception_count = 3

        result = self.service.reconcile(package)

        self.assertEqual(result.status, ReconciliationStatus.RED)
        codes = {d.code for d in result.blocking}
        self.assertIn(DiscrepancyCode.EXCEPTION_COUNT_MISMATCH, codes)
        mismatch = next(
            d for d in result.blocking if d.code == DiscrepancyCode.EXCEPTION_COUNT_MISMATCH
        )
        self.assertEqual(mismatch.expected, "3")
        self.assertEqual(mismatch.actual, "2")

    def test_index_reference_missing_from_detail_sheet_blocks(self) -> None:
        package = sample_package()
        package.index.easements_rights_of_way.append(
            RecordingReference(book="0555", page="900")
        )

        result = self.service.reconcile(package)

        self.assertEqual(result.status, ReconciliationStatus.RED)
        codes = {d.code for d in result.blocking}
        self.assertIn(DiscrepancyCode.INDEX_REFERENCE_NOT_ON_SHEET, codes)

    def test_detail_sheet_reference_missing_from_index_blocks(self) -> None:
        package = sample_package()
        package.index.mortgages = []
        package.cover.declared_mortgage_count = 1

        result = self.service.reconcile(package)

        self.assertEqual(result.status, ReconciliationStatus.RED)
        codes = {d.code for d in result.blocking}
        self.assertIn(DiscrepancyCode.SHEET_REFERENCE_NOT_ON_INDEX, codes)

    def test_recording_key_ignores_leading_zeros(self) -> None:
        package = sample_package()
        package.index.mortgages = [RecordingReference(book="311", page="415")]

        result = self.service.reconcile(package)

        self.assertEqual(result.status, ReconciliationStatus.GREEN)

    def test_low_confidence_extraction_blocks(self) -> None:
        package = sample_package()
        package.mortgages[0].provenance.confidence = ExtractionConfidence.LOW

        result = self.service.reconcile(package)

        self.assertEqual(result.status, ReconciliationStatus.RED)
        codes = {d.code for d in result.blocking}
        self.assertIn(DiscrepancyCode.LOW_CONFIDENCE_EXTRACTION, codes)

    def test_matters_of_concern_are_advisory_not_blocking(self) -> None:
        result = self.service.reconcile(sample_package())

        advisory_codes = {d.code for d in result.advisory}
        self.assertIn(DiscrepancyCode.MATTERS_OF_CONCERN_RAISED, advisory_codes)
        self.assertEqual(result.status, ReconciliationStatus.GREEN)
        self.assertTrue(
            all(d.severity is DiscrepancySeverity.ADVISORY for d in result.advisory)
        )


class CommitmentRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reconciler = ExamReconciliationService()
        self.renderer = CommitmentRenderService()
        self.clause_set = ohio_default_clause_set()

    def _render(self, package: ExamPackage | None = None):
        package = package or sample_package()
        reconciliation = self.reconciler.reconcile(package)
        return self.renderer.render(
            package=package,
            reconciliation=reconciliation,
            clause_set=self.clause_set,
        )

    def _green(self, package: ExamPackage):
        result = self._render(package)
        self.assertIsNotNone(result.draft, result.refusal_reason)
        assert result.draft is not None
        return result.draft

    def test_renders_a_release_requirement_for_each_judgment(self) -> None:
        package = sample_package(
            judgments=[
                JudgmentEntry(
                    debtor="Alex Q. Example",
                    creditor="Example Collections, LLC",
                    case_number="18 CV 2207",
                    court="Example County Court of Common Pleas",
                    amount=Decimal("1250.00"),
                    recording=RecordingReference(book="0402", page="17", document_type="JL"),
                    provenance=_prov(ExamSheetKind.JUDGMENTS, 17),
                ),
                JudgmentEntry(
                    debtor="Jamie Example",
                    creditor="State of Ohio, Department of Taxation",
                    provenance=_prov(ExamSheetKind.JUDGMENTS, 17),
                ),
            ]
        )
        package.cover.declared_judgment_count = 2

        draft = self._green(package)
        judgments = [c for c in draft.schedule_b1 if c.clause_id == "b1.judgment_release"]

        self.assertEqual(len(judgments), 2)
        self.assertEqual(
            judgments[0].text,
            "Release of record of the judgment in favor of Example Collections, LLC, "
            "against Alex Q. Example, in the Example County Court of Common Pleas, Case No. "
            "18 CV 2207, in the amount of $1,250.00, recorded in Official Record 0402, Page 17.",
        )
        # Only what the sheet gives: no empty case, amount, or recording clauses.
        self.assertEqual(
            judgments[1].text,
            "Release of record of the judgment in favor of State of Ohio, Department of "
            "Taxation, against Jamie Example.",
        )
        self.assertEqual(judgments[0].section_header, "Release of the following judgment liens:")
        self.assertIsNone(judgments[1].section_header)
        self.assertEqual(judgments[0].origin, ClauseOrigin.ABSTRACTOR_SHEET)

    def test_exception_wording_follows_the_instrument_kind(self) -> None:
        package = sample_package(
            exceptions=[
                ExceptionEntry(
                    instrument_kinds=[ExceptionInstrumentKind.RESTRICTION],
                    recording=RecordingReference(book="0212", page="58", document_type="DV"),
                    first_party="Example Land Company",
                    second_party="Alex Example",
                    provenance=_prov(ExamSheetKind.EXCEPTIONS, 16),
                ),
                ExceptionEntry(
                    instrument_kinds=[
                        ExceptionInstrumentKind.PLAT,
                        ExceptionInstrumentKind.EASEMENT,
                    ],
                    recording=RecordingReference(book="6-B", page="140", document_type="Plat Book"),
                    first_party="UNREADABLE",
                    second_party="UNREADABLE",
                    instrument_name="Plat of Example Addition",
                    provenance=_prov(ExamSheetKind.EXCEPTIONS, 16),
                ),
            ],
            index=IndexSummarySheet(
                mortgages=[RecordingReference(book="0311", page="415")],
                easements_rights_of_way=[
                    RecordingReference(book="0212", page="58"),
                    RecordingReference(book="6-B", page="140"),
                ],
                provenance=_prov(ExamSheetKind.INDEX_SUMMARY, 19),
            ),
        )

        draft = self._green(package)
        texts = {c.clause_id: c.text for c in draft.schedule_b2}

        self.assertEqual(
            texts["b2.restriction"],
            "Covenants, conditions, restrictions, and reservations as set forth in Deed "
            "Volume 0212, Page 58.",
        )
        self.assertEqual(
            texts["b2.plat"],
            "Terms, conditions, easements, setback lines, and all other matters shown on the "
            "Plat of Example Addition, recorded in Plat Book 6-B, Page 140.",
        )

    def test_illegible_parties_fall_back_to_neutral_wording(self) -> None:
        package = sample_package()
        package.exceptions[0].first_party = "UNREADABLE"
        package.exceptions[0].executed_date = None

        draft = self._green(package)
        texts = [c.text for c in draft.schedule_b2 if c.clause_id == "b2.recorded_instrument"]

        self.assertEqual(len(texts), 1)
        self.assertNotIn("UNREADABLE", texts[0])
        self.assertNotIn("dated ,", " ".join(c.text for c in draft.schedule_b2))

    def test_party_shorthand_is_spelled_out_but_names_are_not_guessed(self) -> None:
        from title_mcp.services.commitment import expand_party

        self.assertEqual(
            expand_party("Alex Q + Jamie Example h/w"), "Alex Q and Jamie Example, husband and wife"
        )
        self.assertEqual(expand_party("Example Power Co"), "Example Power Co.")
        self.assertEqual(expand_party("Example Land Company"), "Example Land Company")

    def test_tax_wording_omits_a_missing_taxpayer(self) -> None:
        package = sample_package()
        for parcel in package.tax_parcels:
            parcel.taxpayer_name = None

        draft = self._green(package)
        taxes = [c.text for c in draft.schedule_b2 if c.clause_id == "b2.tax"]

        self.assertTrue(taxes)
        for text in taxes:
            self.assertNotIn("listed in the name of", text)
            self.assertIn("Taxes for the 1st half of 2025, in the amount of $", text)

    def test_refuses_to_render_when_reconciliation_is_red(self) -> None:
        package = sample_package()
        package.cover.declared_mortgage_count = 4

        result = self._render(package)

        self.assertEqual(result.status, CommitmentRenderStatus.REFUSED)
        self.assertIsNone(result.draft)
        self.assertIn("blocking discrepancy", result.refusal_reason or "")
        self.assertTrue(result.blocking_discrepancies)

    def test_refuses_when_reconciliation_belongs_to_another_file(self) -> None:
        package = sample_package()
        reconciliation = self.reconciler.reconcile(package)
        reconciliation.file_number = "OH-99999-OTHER"

        result = self.renderer.render(
            package=package,
            reconciliation=reconciliation,
            clause_set=self.clause_set,
        )

        self.assertEqual(result.status, CommitmentRenderStatus.REFUSED)
        self.assertIsNone(result.draft)

    def test_renders_schedule_b1_mortgage_in_house_wording(self) -> None:
        result = self._render()
        self.assertEqual(result.status, CommitmentRenderStatus.RENDERED)
        assert result.draft is not None

        b1 = result.draft.schedule_b1
        self.assertEqual(len(b1), 10)

        payoff = b1[-1]
        self.assertEqual(payoff.number, 10)
        self.assertEqual(payoff.origin, ClauseOrigin.ABSTRACTOR_SHEET)
        self.assertEqual(payoff.section_header, "Satisfaction and Release of the following:")
        self.assertEqual(
            payoff.text,
            "Mortgage from Alex Q. Example and Jamie Example, husband and wife, "
            "to Example Savings Bank, in the amount of $100,000.00, dated "
            "January 15, 2010, as recorded in Official Record 0311, Page 415.",
        )

    def test_renders_easement_exceptions_in_house_wording(self) -> None:
        result = self._render()
        assert result.draft is not None

        b2 = result.draft.schedule_b2
        self.assertEqual(len(b2), 15)

        self.assertEqual(
            b2[13].text,
            "Easement and Right of Way granted to Example Power Company, from "
            "Alex Q. and Jamie Example, husband and wife, dated March 3, 1999, recorded in "
            "Official Record 0931, Page 104.",
        )
        self.assertEqual(
            b2[14].text,
            "Easement and Right of Way granted to Example Gas Transmission Company, "
            "from Alex Example and Pat Example, husband and wife, dated June 1, 1955, "
            "recorded in Official Record 0461, Page 212.",
        )

    def test_renders_tax_exception_with_special_assessment(self) -> None:
        result = self._render()
        assert result.draft is not None

        tax_clause = result.draft.schedule_b2[12]
        self.assertEqual(
            tax_clause.text,
            "The Example County Treasurer's 2025 General Tax Duplicate shows:\n\n"
            "Taxes for the 1st half of 2025, listed in the name of Example Alex and "
            "Jamie, in the amount of $1,234.56 are paid.  Taxes for the 2nd half "
            "2025, in the amount of $1,200.44 are paid.\n\n"
            "Special Assessment in the amount of $18.00 is paid.\n\n"
            "Taxes for the year 2026 are a lien but not yet determined, due or "
            "payable.\n\n"
            "Tax Parcel No.: 25-0000.001.\n\n"
            "County taxes are due and payable semi-annually beginning on or about "
            "February 1 and July 1, assessments are due and payable annually beginning "
            "on or about February 1.",
        )

    def test_tax_exception_without_assessment_omits_assessment_language(self) -> None:
        result = self._render()
        assert result.draft is not None

        tax_clause = result.draft.schedule_b2[11]
        self.assertNotIn("Special Assessment", tax_clause.text)
        self.assertTrue(
            tax_clause.text.endswith(
                "County taxes are due and payable semi-annually beginning on or about "
                "February 1 and July 1."
            )
        )

    def test_no_clause_originates_outside_the_abstractor_sheets(self) -> None:
        """The invariant the whole design exists to guarantee.

        Every clause is either agency boilerplate or traceable to a summary sheet a
        human filled in. Nothing is inferred from the underlying documents.
        """

        result = self._render()
        assert result.draft is not None

        for clause in result.draft.clauses:
            self.assertIn(
                clause.origin,
                {ClauseOrigin.STANDARD, ClauseOrigin.ABSTRACTOR_SHEET},
                msg=f"clause {clause.number} has unexpected origin {clause.origin}",
            )

    def test_sheet_derived_clauses_carry_click_through_provenance(self) -> None:
        result = self._render()
        assert result.draft is not None

        derived = [
            c for c in result.draft.clauses if c.origin is ClauseOrigin.ABSTRACTOR_SHEET
        ]
        self.assertEqual(len(derived), 5)
        for clause in derived:
            self.assertIsNotNone(clause.source_sheet)
            self.assertIsNotNone(clause.src_page)

    def test_clause_numbering_is_contiguous_within_each_schedule(self) -> None:
        result = self._render()
        assert result.draft is not None

        for schedule in (result.draft.schedule_b1, result.draft.schedule_b2):
            self.assertEqual(
                [c.number for c in schedule], list(range(1, len(schedule) + 1))
            )

    def test_draft_carries_advisory_discrepancies_forward(self) -> None:
        result = self._render()
        assert result.draft is not None

        advisory = result.draft.source_specific["advisory_discrepancies"]
        self.assertTrue(advisory)
        self.assertTrue(result.draft.requires_human_review)


if __name__ == "__main__":
    unittest.main()


class OrderDataTests(unittest.TestCase):
    """Transaction facts come from the order, never from a document."""

    def setUp(self) -> None:
        self.reconciler = ExamReconciliationService()
        self.renderer = CommitmentRenderService()
        self.clause_set = ohio_default_clause_set()

    def _render(self, order=None, package=None):
        package = package or sample_package()
        return self.renderer.render(
            package=package,
            reconciliation=self.reconciler.reconcile(package),
            clause_set=self.clause_set,
            order=order,
        )

    def test_standard_clause_order_follows_the_alta_form(self) -> None:
        result = self._render()
        assert result.draft is not None
        self.assertEqual(
            [c.clause_id for c in result.draft.schedule_b1[:4]],
            [
                "b1.notify_additional_parties",
                "b1.pay_consideration",
                "b1.pay_premiums",
                "b1.conveyance_documents",
            ],
        )

    def test_form_supplied_clauses_are_flagged_but_keep_their_numbers(self) -> None:
        result = self._render()
        assert result.draft is not None

        supplied = [c for c in result.draft.schedule_b1 if c.form_supplied]
        self.assertEqual([c.number for c in supplied], [1, 2, 3, 4])
        self.assertTrue(result.draft.schedule_b2[0].form_supplied)
        self.assertFalse(any(c.form_supplied for c in result.draft.schedule_b2[1:]))
        # numbering stays contiguous whether or not a form supplies the text
        self.assertEqual(
            [c.number for c in result.draft.schedule_b1],
            list(range(1, len(result.draft.schedule_b1) + 1)),
        )

    def test_without_an_order_there_are_no_sub_items(self) -> None:
        result = self._render()
        assert result.draft is not None
        self.assertIsNone(result.draft.schedule_a)
        self.assertEqual([c for c in result.draft.clauses if c.sub_items], [])

    def test_order_produces_deed_and_new_mortgage_sub_items(self) -> None:
        result = self._render(order=sample_order())
        assert result.draft is not None

        conveyance = next(
            c for c in result.draft.schedule_b1
            if c.clause_id == "b1.conveyance_documents"
        )
        self.assertEqual([s.label for s in conveyance.sub_items], ["a.", "b."])
        self.assertEqual(
            conveyance.sub_items[0].text,
            "Deed from Alex Q. Example and Jamie Example, husband and wife, to "
            "Sam Sample and Robin Sample, husband and wife, with contractual "
            "rights under a purchase agreement(s) with the vested owner, conveying the "
            "property described herein in fee simple, free and unencumbered.",
        )
        self.assertEqual(
            conveyance.sub_items[1].text,
            "Mortgage from Sam Sample and Robin Sample, husband and wife, to "
            "Example Federal Credit Union, in the sum of $80,000.00, pertaining to the "
            "premises described in Exhibit A hereof.",
        )

    def test_sub_items_are_order_data_and_nothing_else(self) -> None:
        result = self._render(order=sample_order())
        assert result.draft is not None

        subs = [s for c in result.draft.clauses for s in c.sub_items]
        self.assertTrue(subs)
        for sub in subs:
            self.assertIs(sub.origin, ClauseOrigin.ORDER_DATA)

    def test_missing_lender_omits_only_the_mortgage_sub_item(self) -> None:
        order = sample_order(lender=None, loan_amount=None)
        result = self._render(order=order)
        assert result.draft is not None

        conveyance = next(
            c for c in result.draft.schedule_b1
            if c.clause_id == "b1.conveyance_documents"
        )
        self.assertEqual([s.label for s in conveyance.sub_items], ["a."])

    def test_schedule_a_is_built_from_the_order(self) -> None:
        result = self._render(order=sample_order())
        assert result.draft is not None

        sched_a = result.draft.schedule_a
        assert sched_a is not None
        self.assertEqual(sched_a.commitment_date, "September 1, 2026 at 8:00 A.M.")
        self.assertEqual(sched_a.estate, "Fee Simple")
        self.assertEqual(len(sched_a.policies), 2)
        self.assertEqual(sched_a.policies[1].amount_of_insurance, Decimal("80000.00"))
        self.assertIsNone(sched_a.policies[0].amount_of_insurance)

    def test_refuses_when_the_order_belongs_to_another_file(self) -> None:
        result = self._render(order=sample_order(file_number="OH-99999-OTHER"))
        self.assertEqual(result.status, CommitmentRenderStatus.REFUSED)
        self.assertIsNone(result.draft)
        self.assertIn("Order belongs to file", result.refusal_reason or "")

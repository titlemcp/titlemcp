from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.exam import (
    ExamPackage,
    ExamSheetKind,
    ExtractionConfidence,
    FieldProvenance,
)
from title_mcp.domain.title import RecordingReference


class DiscrepancySeverity(StrEnum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class DiscrepancyCode(StrEnum):
    MORTGAGE_COUNT_MISMATCH = "mortgage_count_mismatch"
    JUDGMENT_COUNT_MISMATCH = "judgment_count_mismatch"
    EXCEPTION_COUNT_MISMATCH = "exception_count_mismatch"
    INDEX_REFERENCE_NOT_ON_SHEET = "index_reference_not_on_sheet"
    SHEET_REFERENCE_NOT_ON_INDEX = "sheet_reference_not_on_index"
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    MISSING_LAST_SHOWN_OWNER_TRANSFER = "missing_last_shown_owner_transfer"
    MATTERS_OF_CONCERN_RAISED = "matters_of_concern_raised"


class ReconciliationStatus(StrEnum):
    GREEN = "green"
    RED = "red"


def recording_key(reference: RecordingReference) -> str:
    """Normalized identity for a recording reference, for set comparison."""

    if reference.instrument_number:
        return f"inst:{reference.instrument_number.strip().upper()}"
    book = (reference.book or "").strip().upper().lstrip("0")
    page = (reference.page or "").strip().upper().lstrip("0")
    return f"bp:{book}/{page}"


class Discrepancy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: DiscrepancyCode
    severity: DiscrepancySeverity
    message: str
    expected: str | None = None
    actual: str | None = None
    src_pages: list[int] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    """Canonical record for the internal-consistency check on an exam package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.exam_reconciliation"
    schema_version: str = "1.0"
    record_type: str = "exam_reconciliation"
    file_number: str
    status: ReconciliationStatus
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)

    @property
    def blocking(self) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.severity == DiscrepancySeverity.BLOCKING]

    @property
    def advisory(self) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.severity == DiscrepancySeverity.ADVISORY]


class ExamReconciliationService:
    """Cross-checks an exam package against itself.

    The abstractor states the same facts three times: as declared counts on the
    cover sheet, as enumerated rows on the detail sheets, and as book/page
    references on the index page. Agreement across all three is what licenses
    downstream automation. Disagreement is a human's problem, not a model's.

    This service contains no model calls and makes no title determinations. It
    compares what a person already wrote down.
    """

    def reconcile(self, package: ExamPackage) -> ReconciliationResult:
        discrepancies: list[Discrepancy] = []
        checks: list[str] = []

        discrepancies.extend(self._check_declared_counts(package))
        checks.append("declared_counts")

        if package.index is not None:
            discrepancies.extend(self._check_index_cross_reference(package))
            checks.append("index_cross_reference")

        discrepancies.extend(self._check_extraction_confidence(package))
        checks.append("extraction_confidence")

        discrepancies.extend(self._check_review_signals(package))
        checks.append("review_signals")

        blocking = [d for d in discrepancies if d.severity == DiscrepancySeverity.BLOCKING]
        return ReconciliationResult(
            file_number=package.file_number,
            status=ReconciliationStatus.RED if blocking else ReconciliationStatus.GREEN,
            discrepancies=discrepancies,
            checks_run=checks,
            requires_human_review=True,
        )

    def _check_declared_counts(self, package: ExamPackage) -> list[Discrepancy]:
        cover = package.cover
        pairs = (
            (
                DiscrepancyCode.MORTGAGE_COUNT_MISMATCH,
                "mortgage",
                cover.declared_mortgage_count,
                len(package.mortgages),
            ),
            (
                DiscrepancyCode.JUDGMENT_COUNT_MISMATCH,
                "judgment",
                cover.declared_judgment_count,
                len(package.judgments),
            ),
            (
                DiscrepancyCode.EXCEPTION_COUNT_MISMATCH,
                "exception",
                cover.declared_exception_count,
                len(package.exceptions),
            ),
        )

        found: list[Discrepancy] = []
        for code, label, declared, actual in pairs:
            if declared == actual:
                continue
            found.append(
                Discrepancy(
                    code=code,
                    severity=DiscrepancySeverity.BLOCKING,
                    message=(
                        f"Cover sheet declares {declared} {label}(s); "
                        f"the detail sheet enumerates {actual}."
                    ),
                    expected=str(declared),
                    actual=str(actual),
                    src_pages=[cover.provenance.src_page],
                )
            )
        return found

    def _check_index_cross_reference(self, package: ExamPackage) -> list[Discrepancy]:
        index = package.index
        if index is None:
            return []

        found: list[Discrepancy] = []
        groups = (
            ("mortgage", index.mortgages, [m.recording for m in package.mortgages]),
            (
                "easement/right-of-way",
                index.easements_rights_of_way,
                [e.recording for e in package.exceptions],
            ),
        )

        for label, index_refs, sheet_refs in groups:
            index_keys = {recording_key(ref): ref for ref in index_refs}
            sheet_keys = {recording_key(ref): ref for ref in sheet_refs}

            for key, ref in index_keys.items():
                if key in sheet_keys:
                    continue
                found.append(
                    Discrepancy(
                        code=DiscrepancyCode.INDEX_REFERENCE_NOT_ON_SHEET,
                        severity=DiscrepancySeverity.BLOCKING,
                        message=(
                            f"Index page lists {label} {ref.display}, "
                            "which does not appear on the detail sheet."
                        ),
                        expected=ref.display,
                        src_pages=[index.provenance.src_page],
                    )
                )

            for key, ref in sheet_keys.items():
                if key in index_keys:
                    continue
                found.append(
                    Discrepancy(
                        code=DiscrepancyCode.SHEET_REFERENCE_NOT_ON_INDEX,
                        severity=DiscrepancySeverity.BLOCKING,
                        message=(
                            f"Detail sheet lists {label} {ref.display}, "
                            "which does not appear on the index page."
                        ),
                        actual=ref.display,
                        src_pages=[index.provenance.src_page],
                    )
                )
        return found

    def _check_extraction_confidence(self, package: ExamPackage) -> list[Discrepancy]:
        found: list[Discrepancy] = []
        for label, provenance in self._provenances(package):
            if provenance.confidence != ExtractionConfidence.LOW:
                continue
            found.append(
                Discrepancy(
                    code=DiscrepancyCode.LOW_CONFIDENCE_EXTRACTION,
                    severity=DiscrepancySeverity.BLOCKING,
                    message=(
                        f"{label} was extracted with low confidence and must be "
                        "confirmed against the scan before it can be used."
                    ),
                    src_pages=[provenance.src_page],
                )
            )
        return found

    def _check_review_signals(self, package: ExamPackage) -> list[Discrepancy]:
        found: list[Discrepancy] = []
        cover = package.cover

        if cover.matters_of_concern:
            found.append(
                Discrepancy(
                    code=DiscrepancyCode.MATTERS_OF_CONCERN_RAISED,
                    severity=DiscrepancySeverity.ADVISORY,
                    message=(
                        f"The abstractor raised {len(cover.matters_of_concern)} matter(s) "
                        "of concern for the reviewing attorney."
                    ),
                    src_pages=[cover.provenance.src_page],
                )
            )

        if cover.last_shown_owner_transfer is None:
            found.append(
                Discrepancy(
                    code=DiscrepancyCode.MISSING_LAST_SHOWN_OWNER_TRANSFER,
                    severity=DiscrepancySeverity.ADVISORY,
                    message="No last shown owner transfer was recorded on the cover sheet.",
                    src_pages=[cover.provenance.src_page],
                )
            )
        return found

    @staticmethod
    def _provenances(package: ExamPackage) -> list[tuple[str, FieldProvenance]]:
        items: list[tuple[str, FieldProvenance]] = [
            (f"Cover sheet ({ExamSheetKind.SEARCH_COVER.value})", package.cover.provenance)
        ]
        items.extend(
            (f"Mortgage {entry.recording.display}", entry.provenance)
            for entry in package.mortgages
        )
        items.extend(
            (f"Exception {entry.recording.display}", entry.provenance)
            for entry in package.exceptions
        )
        items.extend(
            (f"Judgment against {entry.debtor}", entry.provenance) for entry in package.judgments
        )
        items.extend(
            (f"Tax parcel {entry.parcel_id}", entry.provenance) for entry in package.tax_parcels
        )
        if package.index is not None:
            items.append(("Index page", package.index.provenance))
        return items

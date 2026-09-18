from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.exam import (
    ExamPackage,
    ExamSheetKind,
    ExtractionConfidence,
    FieldProvenance,
    UncertainReading,
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
    INDEX_NOT_CORROBORATED = "index_not_corroborated"
    UNCERTAIN_READING = "uncertain_reading"
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    MISSING_LAST_SHOWN_OWNER_TRANSFER = "missing_last_shown_owner_transfer"
    MATTERS_OF_CONCERN_RAISED = "matters_of_concern_raised"


class ReconciliationStatus(StrEnum):
    GREEN = "green"
    RED = "red"


# Fields whose doubt cannot reach the commitment: free text, reviewer aids,
# Schedule A facts (confirmed against the order separately), and index entries
# (a doubtful index entry surfaces through the cross-check).
_NON_BEARING = {
    ExamSheetKind.SEARCH_COVER: {
        "matters_of_concern", "notes", "completed_by", "completed_date", "search_start_date",
        "order_number", "src_text", "lsot_book", "lsot_page", "auditor_owners", "buyers",
        "property_line1", "property_city", "property_postal_code", "state",
    },
    ExamSheetKind.INDEX_SUMMARY: {"name_searches", "src_text"},
    # The record series only labels the citation ("Deed Volume" or "Official Record").
    ExamSheetKind.EXCEPTIONS: {"record_series", "notes", "src_text"},
}

_ABSENT = re.compile(
    r"^\s*(?:|null|none|n/?a|blank|\(.*\)|not (?:written|shown|stated|present).*|no .*box.*)\s*$",
    re.IGNORECASE,
)


# Where an extracted field's value lives on the record, when the names differ.
_FIELD_PATHS = {
    "book": ("recording", "book"),
    "page": ("recording", "page"),
    "recorded_date": ("recording", "recorded_date"),
    "record_series": ("recording", "document_type"),
    "amount": ("original_amount",),
    "property_line1": ("property_address", "line1"),
    "property_city": ("property_address", "city"),
    "property_postal_code": ("property_address", "postal_code"),
    "lsot_book": ("last_shown_owner_transfer", "book"),
    "lsot_page": ("last_shown_owner_transfer", "page"),
}


def stored_value(entry: Any, field: str) -> str | None:
    """The value a record holds for an extracted field, as drafting prints it."""

    name = field.strip().lower()
    path = _FIELD_PATHS.get(name, (name,))
    if name == "amount" and hasattr(entry, "amount"):
        path = ("amount",)
    value: Any = entry
    for part in path:
        value = getattr(value, part, None)
        if value is None:
            return None
    if isinstance(value, date):
        return f"{value.month}/{value.day}/{value.year}"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(getattr(v, "value", v)) for v in value)
    return str(getattr(value, "value", value))


def _yes_no_key(value: str) -> str:
    """A yes/no field's answer: "Y 3450" and "yes" are both yes."""

    text = value.strip().lower()
    if re.match(r"^(?:y|yes|x|true|checked)\b", text):
        return "yes"
    if re.match(r"^(?:n|no|false|unchecked)\b", text):
        return "no"
    return _value_key(value)


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{2}|\d{4})\s*$")


def _date_key(value: str) -> str:
    """A written date by month, day, and two-digit year: "5/1/39" is "5/1/2039"."""

    m = _NUMERIC_DATE.match(value)
    if not m:
        return _value_key(value)
    return f"{int(m[1])}/{int(m[2])}/{int(m[3]) % 100:02d}"


def _value_key(value: str) -> str:
    """A value with formatting removed: case, punctuation, separators, spacing."""

    return re.sub(r"[^a-z0-9]", "", value.lower()).lstrip("0")


def is_real_doubt(
    doubt: UncertainReading,
    known: list[KnownConfusion] | tuple[KnownConfusion, ...] = (),
    used: str | None = None,
) -> bool:
    """Whether a reported doubt could change a value.

    Not a doubt: an absent value ("(not written)", "no count box"), or
    alternatives that differ from the reading only in formatting ("9.8.26" and
    "9-8-26", "$9121.47" and "$9,121.47", a capital letter).
    """

    read = doubt.read_as or ""
    if _ABSENT.match(read):
        return False
    return bool(distinct_alternatives(doubt, known, used))


# Fields holding a person's or company's name.
_NAME_FIELDS = {
    "first_party", "second_party", "borrowers", "lender", "debtor", "creditor",
    "auditor_owners", "buyers", "taxpayer_name", "parties",
}
_SPOUSE_NOTATION = re.compile(r"\b(?:h/w|w/h|husband and wife|wife and husband)\b", re.IGNORECASE)


def _name_key(value: str) -> str:
    """A name with shorthand spelled out, so "A + B h/w" and "A and B, husband and
    wife" compare equal."""

    text = _SPOUSE_NOTATION.sub(" husbandandwife ", value)
    text = re.sub(r"\s*\+\s*|\s*&\s*", " and ", text)
    return _value_key(text)


class KnownConfusion(BaseModel):
    """A misreading known to be harmless: what is written, and what a reader takes it for.

    A doubt is set aside only when the difference between the value used and an
    alternative is exactly this substitution. Each entry is explicit and
    reviewable, so nothing is dismissed by a guess.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reads: str = Field(min_length=1, description="What is actually written, e.g. 'h/w'.")
    misread_as: str = Field(min_length=1, description="What a reader may take it for, e.g. '4/w'.")
    fields: list[str] = Field(
        default_factory=list, description="Limit to these fields; empty means any field."
    )

    def explains(self, field: str, used: str, alternative: str) -> bool:
        if self.fields and field.strip().lower() not in {f.lower() for f in self.fields}:
            return False
        token = re.compile(rf"(?<![\w/]){re.escape(self.reads)}(?![\w/])", re.IGNORECASE)
        if not token.search(used):
            return False
        if alternative.strip().lower() == self.misread_as.lower():
            return True  # the reader offered only the misread fragment
        swapped = token.sub(self.misread_as, used)
        return _value_key(swapped) == _value_key(alternative)


def distinct_alternatives(
    doubt: UncertainReading,
    known: list[KnownConfusion] | tuple[KnownConfusion, ...] = (),
    used: str | None = None,
) -> list[str]:
    """The alternatives that would actually change the value, in the reader's order.

    Dropped: formatting-only differences, absent values, a difference only in
    spouse notation or "+" for a name, and a difference that a known confusion
    fully explains.
    """

    read = doubt.read_as or ""
    base = used or read
    name = doubt.field.strip().lower()
    is_name = name in _NAME_FIELDS
    if base in ("yes", "no"):
        key = _yes_no_key  # the record holds only yes or no
    elif is_name:
        key = _name_key
    elif name.endswith("date"):
        key = _date_key
    else:
        key = _value_key
    seen = {key(base)}
    out: list[str] = []
    # What the reader saw is itself an alternative when the record differs from it.
    for alt in [read, *doubt.alternatives]:
        k = key(alt)
        if k in seen or _ABSENT.match(alt):
            continue
        if any(c.explains(doubt.field, base, alt) for c in known):
            continue
        seen.add(k)
        out.append(alt)
    return out


def _reaches_commitment(sheet: ExamSheetKind, field: str) -> bool:
    name = field.strip().lower()
    if sheet == ExamSheetKind.INDEX_SUMMARY:
        return False
    return name not in _NON_BEARING.get(sheet, {"notes", "src_text"})


def _cited(reference: RecordingReference) -> bool:
    return bool(reference.instrument_number or reference.book or reference.page)


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
    field: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    used: str | None = None
    """For a doubtful reading: the value the record holds, which drafting used."""


class ReconciliationChecks(BaseModel):
    """Which checks an abstractor's forms support.

    Package formats differ. One abstractor's cover sheet declares counts and the
    package carries an index page; another's typed report has neither. Running a
    check the form cannot satisfy produces false discrepancies that bury real
    ones, so a caller that knows the form can switch such checks off. Skipped
    checks are recorded in ``checks_run``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    declared_counts: bool = True
    index_cross_reference: bool = True


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

    def reconcile(
        self,
        package: ExamPackage,
        checks_enabled: ReconciliationChecks | None = None,
        known_confusions: list[KnownConfusion] | None = None,
    ) -> ReconciliationResult:
        enabled = checks_enabled or ReconciliationChecks()
        suppressed: list[dict[str, Any]] = []
        discrepancies: list[Discrepancy] = []
        checks: list[str] = []

        if enabled.declared_counts:
            discrepancies.extend(self._check_declared_counts(package))
            checks.append("declared_counts")
        else:
            checks.append("declared_counts:not_supported_by_form")

        if package.index is not None and enabled.index_cross_reference:
            discrepancies.extend(self._check_index_cross_reference(package))
            checks.append("index_cross_reference")
        elif package.index is not None:
            checks.append("index_cross_reference:not_supported_by_form")

        discrepancies.extend(
            self._check_extraction_confidence(package, known_confusions or [], suppressed)
        )
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
            source_specific={"suppressed_doubts": suppressed} if suppressed else {},
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
            if declared is None or declared == actual:
                continue  # not stated on this form, or agrees
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

        # A genuine index shares most of its references with the detail sheets. A
        # page read as the index that shares none of them is not this package's
        # index (a name-search printout, a typed report page); cross-checking
        # against it would only report every reference as missing.
        index_refs_all = [*index.mortgages, *index.easements_rights_of_way]
        sheet_refs_all = [
            *(m.recording for m in package.mortgages),
            *(e.recording for e in package.exceptions),
        ]
        all_index = {recording_key(r) for r in index_refs_all if _cited(r)}
        all_sheet = {recording_key(r) for r in sheet_refs_all if _cited(r)}
        # An index that lists nothing cannot corroborate anything either. A single
        # sheet reference against a single different index entry is left to the
        # cross-check below: that is a genuine disagreement, not a wrong page.
        empty_index = not all_index and bool(all_sheet)
        unrelated = bool(all_index) and len(all_sheet) >= 2 and not (all_index & all_sheet)
        if empty_index or unrelated:
            return [
                Discrepancy(
                    code=DiscrepancyCode.INDEX_NOT_CORROBORATED,
                    severity=DiscrepancySeverity.ADVISORY,
                    message=(
                        "The page read as the index "
                        + (
                            "lists no references"
                            if empty_index
                            else "shares no references with the detail sheets"
                        )
                        + ", so it was not used to cross-check them."
                    ),
                    src_pages=[index.provenance.src_page],
                )
            ]

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
            # An unrecorded instrument has no reference to find on an index.
            index_keys = {recording_key(ref): ref for ref in index_refs if _cited(ref)}
            sheet_keys = {recording_key(ref): ref for ref in sheet_refs if _cited(ref)}

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

    def _check_extraction_confidence(
        self,
        package: ExamPackage,
        known: list[KnownConfusion],
        suppressed: list[dict[str, Any]],
    ) -> list[Discrepancy]:
        """One question per value in doubt; blocking only where it reaches the commitment.

        A reader that names its doubts ("county read as Exampel, could be Example") gets
        each checked on its own. Only a low-confidence read with no doubt named falls
        back to asking for the whole entry to be checked.
        """

        found: list[Discrepancy] = []
        for label, entry, provenance in self._entries(package):
            doubts = []
            for d in provenance.uncertain:
                used = stored_value(entry, d.field)
                if is_real_doubt(d, known, used):
                    doubts.append(d)
                elif is_real_doubt(d, (), used):
                    # Real but for a known, harmless confusion: set aside, on record.
                    suppressed.append(
                        {"entry": label, "field": d.field, "used": used or d.read_as,
                         "alternatives": d.alternatives}
                    )
            for doubt in doubts:
                blocking = _reaches_commitment(provenance.sheet, doubt.field)
                distinct = distinct_alternatives(doubt, known, stored_value(entry, doubt.field))
                alts = " or ".join(distinct)
                could_be = f"; could be {alts}" if alts else ""
                why = f" ({doubt.reason})" if doubt.reason else ""
                found.append(
                    Discrepancy(
                        code=DiscrepancyCode.UNCERTAIN_READING,
                        severity=(
                            DiscrepancySeverity.BLOCKING
                            if blocking
                            else DiscrepancySeverity.ADVISORY
                        ),
                        message=(
                            f"{label}: {doubt.field.replace('_', ' ')} read as "
                            f"'{doubt.read_as or ''}'{could_be}{why}."
                        ),
                        actual=doubt.read_as,
                        field=doubt.field,
                        alternatives=distinct,
                        used=stored_value(entry, doubt.field),
                        src_pages=[provenance.src_page],
                    )
                )
            if provenance.confidence != ExtractionConfidence.LOW or doubts:
                continue
            found.append(
                Discrepancy(
                    code=DiscrepancyCode.LOW_CONFIDENCE_EXTRACTION,
                    severity=DiscrepancySeverity.BLOCKING,
                    message=(
                        f"{label} was extracted with low confidence, and the reader did not "
                        "say which value; check its transcription against the scan."
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
    def _entries(package: ExamPackage) -> list[tuple[str, Any, FieldProvenance]]:
        items: list[tuple[str, Any, FieldProvenance]] = [
            ("Cover sheet", package.cover, package.cover.provenance)
        ]
        items.extend(
            (f"Mortgage {e.recording.display}", e, e.provenance) for e in package.mortgages
        )
        items.extend(
            (f"Exception {e.recording.display}", e, e.provenance) for e in package.exceptions
        )
        items.extend((f"Judgment against {e.debtor}", e, e.provenance) for e in package.judgments)
        items.extend((f"Tax parcel {e.parcel_id}", e, e.provenance) for e in package.tax_parcels)
        if package.index is not None:
            items.append(("Index page", package.index, package.index.provenance))
        return items

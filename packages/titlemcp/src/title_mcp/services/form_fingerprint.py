"""Identify an abstractor's forms by their structure, never by who made them.

A form is known by its pre-printed field labels ("Parcel Number", "Short Legal
Desc.", "CAUV?"), not by its letterhead. The fingerprint is a hash of those
labels, normalized, so the same blank form yields the same fingerprint whoever
filled it in, and a revised form yields a new one. Profiles of what a form
supports can then be kept per fingerprint, with no company recorded anywhere.

A fingerprint is a pseudonym, not anonymity: anyone holding a blank copy of a
form can compute it. Treat a store of fingerprints as confidential.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from title_mcp.domain.exam import ExamSheetKind
from title_mcp.services.exam import ReconciliationChecks
from title_mcp.sources.base import SourceResultStatus

FINGERPRINT_VERSION = "1"

# Labels that could name or locate the form's owner are dropped before hashing,
# whatever the reader returned.
_IDENTIFYING = re.compile(
    r"@|https?:|www\.|\.com\b|\.net\b|\.org\b"  # contact details
    r"|\(?\d{3}\)?[\s.-]*\d{3}[\s.-]?\d{4}"  # phone numbers
    r"|\b\d{5}(?:-\d{4})?\b"  # ZIP codes
    r"|\b\d+\s+[A-Za-z]+\s+(?:st|street|ave|avenue|rd|road|dr|drive|blvd|suite|ste)\b"  # street
    r"|\b(?:llc|inc|corp|corporation|company|co\.|agency|abstract(?:ing|ors?)?|associates"
    r"|services|group|partners|ltd|lp|llp|pllc)\b",
    re.IGNORECASE,
)
_MAX_LABEL_WORDS = 8


class SheetLayout(BaseModel):
    """The pre-printed labels of one summary sheet, as a reader transcribed them."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    page_number: int = Field(ge=1)
    sheet: ExamSheetKind
    labels: list[str] = Field(
        default_factory=list,
        description=(
            "Every pre-printed field label and printed heading on the form, in reading "
            "order. Exclude the letterhead, logos, and any company, person, address, "
            "phone, email, or web address. Exclude anything handwritten or typed into a "
            "field."
        ),
    )
    has_count_boxes: bool = Field(
        default=False,
        description=(
            "True when the form has printed boxes for the number of mortgages, "
            "judgments, or exceptions found."
        ),
    )


class FormLayouts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheets: list[SheetLayout] = Field(default_factory=list)


class FormFingerprintResult(BaseModel):
    """Canonical record for the form fingerprint of one exam package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.form_fingerprint"
    schema_version: str = FINGERPRINT_VERSION
    record_type: str = "form_fingerprint"
    file_number: str
    status: SourceResultStatus
    form_fingerprint: str | None = None
    sheet_fingerprints: dict[int, str] = Field(default_factory=dict)
    layouts: list[SheetLayout] = Field(default_factory=list)
    checks: ReconciliationChecks = Field(default_factory=ReconciliationChecks)
    warnings: list[str] = Field(default_factory=list)
    source_specific: dict[str, Any] = Field(default_factory=dict)


def fingerprint_result(file_number: str, layouts: list[SheetLayout]) -> FormFingerprintResult:
    return FormFingerprintResult(
        file_number=file_number,
        status=SourceResultStatus.SUCCEEDED if layouts else SourceResultStatus.NO_RESULTS,
        form_fingerprint=form_fingerprint(layouts),
        sheet_fingerprints={s.page_number: sheet_fingerprint(s) for s in layouts},
        layouts=[s.model_copy(update={"labels": sorted(label_set(s))}) for s in layouts],
        checks=derive_checks(layouts),
    )


def normalize_label(label: str) -> str | None:
    """A label as it counts toward the fingerprint, or None if it must not."""

    text = label.strip()
    if not text or _IDENTIFYING.search(text) or len(text.split()) > _MAX_LABEL_WORDS:
        return None
    text = re.sub(r"[^a-z ]", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) >= 2 else None


def label_set(layout: SheetLayout) -> frozenset[str]:
    return frozenset(n for n in map(normalize_label, layout.labels) if n)


def sheet_fingerprint(layout: SheetLayout) -> str:
    """Fingerprint of one sheet's form: its kind plus its normalized labels."""

    body = "\n".join([f"v{FINGERPRINT_VERSION}", layout.sheet.value, *sorted(label_set(layout))])
    return "sheet:" + hashlib.sha256(body.encode()).hexdigest()[:16]


def package_fingerprint(layouts: list[SheetLayout]) -> str | None:
    """Fingerprint of a package's form family: the set of its sheet fingerprints."""

    prints = sorted({sheet_fingerprint(s) for s in layouts if label_set(s)})
    if not prints:
        return None
    body = "\n".join([f"v{FINGERPRINT_VERSION}", *prints])
    return "form:" + hashlib.sha256(body.encode()).hexdigest()[:16]


def similarity(a: SheetLayout, b: SheetLayout) -> float:
    """Jaccard similarity of two sheets' labels; 1.0 is the same form."""

    if a.sheet != b.sheet:
        return 0.0
    la, lb = label_set(a), label_set(b)
    if not la and not lb:
        return 1.0
    return len(la & lb) / len(la | lb)


def derive_checks(layouts: list[SheetLayout]) -> ReconciliationChecks:
    """The reconciliation checks a form family can satisfy, read from the forms.

    Declared counts are checked only when the cover sheet prints count boxes. The
    index cross-reference runs whenever an index page was found; whether that page
    really is the package's index is judged by reconciliation from the references
    it shares with the detail sheets, which no label can tell.
    """

    covers = [s for s in layouts if s.sheet == ExamSheetKind.SEARCH_COVER]
    return ReconciliationChecks(
        declared_counts=any(s.has_count_boxes for s in covers),
        index_cross_reference=any(s.sheet == ExamSheetKind.INDEX_SUMMARY for s in layouts),
    )


def form_fingerprint(layouts: list[SheetLayout]) -> str | None:
    """The form's identity: its cover sheet, which every package has.

    Which other sheets a package carries varies file to file, so they do not
    identify the form. Without a readable cover, the first sheet stands in.
    """

    covers = [s for s in layouts if s.sheet == ExamSheetKind.SEARCH_COVER and label_set(s)]
    anchor = covers[0] if covers else next((s for s in layouts if label_set(s)), None)
    return sheet_fingerprint(anchor).replace("sheet:", "form:", 1) if anchor else None

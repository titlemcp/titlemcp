from __future__ import annotations

import unittest

from title_mcp.domain.exam import ExamSheetKind
from title_mcp.services.form_fingerprint import (
    SheetLayout,
    derive_checks,
    form_fingerprint,
    normalize_label,
    package_fingerprint,
    sheet_fingerprint,
    similarity,
)

COVER_LABELS = [
    "County",
    "Auditors Owner(s):",
    "Buyer(s):",
    "Property Address:",
    "Start Date:",
    "MTG:",
    "Judgment:",
    "Exceptions:",
    "Completed:",
    "By:",
]


def cover(labels: list[str] | None = None, boxes: bool = True, page: int = 1) -> SheetLayout:
    return SheetLayout(
        page_number=page,
        sheet=ExamSheetKind.SEARCH_COVER,
        labels=list(COVER_LABELS if labels is None else labels),
        has_count_boxes=boxes,
    )


class FingerprintTests(unittest.TestCase):
    def test_same_form_same_fingerprint_whatever_the_order_or_case(self) -> None:
        a = cover()
        b = cover([label.upper() for label in reversed(COVER_LABELS)], page=7)
        self.assertEqual(sheet_fingerprint(a), sheet_fingerprint(b))
        self.assertEqual(package_fingerprint([a]), package_fingerprint([b]))

    def test_identifying_text_never_reaches_the_fingerprint(self) -> None:
        for label in (
            "Example Abstract Services, LLC",
            "123 Example Road, Suite 4",
            "Phone (555) 555-0100",
            "orders@example.com",
            "www.example.com",
            "Exampleville, OH 00000",
        ):
            self.assertIsNone(normalize_label(label), label)
        leaky = cover([*COVER_LABELS, "Example Abstract Services, LLC", "(555) 555-0100"])
        self.assertEqual(sheet_fingerprint(leaky), sheet_fingerprint(cover()))

    def test_a_revised_form_is_new_but_similar(self) -> None:
        revised = cover([*COVER_LABELS, "Flood Zone:"])
        self.assertNotEqual(sheet_fingerprint(revised), sheet_fingerprint(cover()))
        self.assertGreater(similarity(revised, cover()), 0.85)
        other = SheetLayout(page_number=2, sheet=ExamSheetKind.TAX, labels=COVER_LABELS)
        self.assertEqual(similarity(other, cover()), 0.0, "different sheet kinds never match")

    def test_checks_are_derived_from_the_form(self) -> None:
        index = SheetLayout(
            page_number=19,
            sheet=ExamSheetKind.INDEX_SUMMARY,
            labels=["MORTGAGES", "LEASES/AGMTS", "EASEMENTS/ROW"],
        )
        full = derive_checks([cover(), index])
        self.assertTrue(full.declared_counts and full.index_cross_reference)

        typed = derive_checks([cover(["Search Report", "Parcel #", "Borrower"], boxes=False)])
        self.assertFalse(typed.declared_counts or typed.index_cross_reference)

    def test_the_cover_sheet_identifies_the_form(self) -> None:
        tax = SheetLayout(page_number=3, sheet=ExamSheetKind.TAX, labels=["Parcel Number", "CAUV?"])
        self.assertEqual(
            form_fingerprint([cover()]),
            form_fingerprint([cover(page=2), tax]),
            "which other sheets a package carries does not change the form",
        )
        self.assertTrue((form_fingerprint([cover()]) or "").startswith("form:"))

    def test_empty_layouts_have_no_package_fingerprint(self) -> None:
        self.assertIsNone(package_fingerprint([]))
        self.assertIsNone(package_fingerprint([cover([])]))


if __name__ == "__main__":
    unittest.main()


class _FakeLayoutClient:
    def __init__(self, layouts: list[SheetLayout] | None = None, fail: bool = False) -> None:
        self.layouts = layouts or []
        self.fail = fail
        self.images: int = 0

    def extract(self, *, instruction, images, schema):  # noqa: ANN001
        if self.fail:
            raise RuntimeError("upstream failure")
        self.images = len(images)
        return schema(sheets=self.layouts)


class FingerprintServiceTests(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        from title_mcp.services.exam_extraction import ExamExtractionRequest, SheetImage

        pages = [SheetImage(page_number=n, data_base64="ZmFrZQ==") for n in (1, 2, 3)]
        return ExamExtractionRequest(file_number="OH-00000-SAMPLE", pages=pages)

    def _assignments(self):
        from title_mcp.services.exam_extraction import PageAssignment

        return [
            PageAssignment(page_number=1, sheet=ExamSheetKind.SEARCH_COVER),
            PageAssignment(page_number=3, sheet=None),
        ]

    async def test_canonical_record_from_the_forms(self) -> None:
        from title_mcp.services.exam_extraction import ClaudeExamExtractionService
        from title_mcp.sources.base import SourceResultStatus

        leaky = cover([*COVER_LABELS, "Example Abstract Services, LLC"])
        client = _FakeLayoutClient([leaky])
        result = await ClaudeExamExtractionService(client=client).fingerprint_forms(
            self._request(), self._assignments()
        )

        self.assertEqual(result.schema_name, "title_mcp.form_fingerprint")
        self.assertEqual(result.record_type, "form_fingerprint")
        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(client.images, 1, "only pages classified as summary sheets are read")
        self.assertEqual(result.form_fingerprint, form_fingerprint([cover()]))
        self.assertTrue(result.checks.declared_counts)
        stored = " ".join(label for s in result.layouts for label in s.labels)
        self.assertNotIn("example abstract", stored, "identifying labels are not kept")

    async def test_missing_credentials_requires_configuration(self) -> None:
        from title_mcp.services.exam_extraction import ClaudeExamExtractionService
        from title_mcp.settings import TitleMCPSettings
        from title_mcp.sources.base import SourceResultStatus

        service = ClaudeExamExtractionService(settings=TitleMCPSettings(anthropic_api_key=None))
        result = await service.fingerprint_forms(self._request(), self._assignments())
        self.assertEqual(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)

    async def test_client_failure_is_reported_not_raised(self) -> None:
        from title_mcp.services.exam_extraction import ClaudeExamExtractionService
        from title_mcp.sources.base import SourceResultStatus

        service = ClaudeExamExtractionService(client=_FakeLayoutClient(fail=True))
        result = await service.fingerprint_forms(self._request(), self._assignments())
        self.assertEqual(result.status, SourceResultStatus.FAILED)
        self.assertIsNone(result.form_fingerprint)

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from title_mcp.domain.exam import ExamSheetKind, ExtractionConfidence
from title_mcp.services.clause_sets import ohio_default_clause_set
from title_mcp.services.commitment import CommitmentRenderService, CommitmentRenderStatus
from title_mcp.services.exam import ExamReconciliationService, ReconciliationStatus
from title_mcp.services.exam_extraction import (
    ClaudeExamExtractionClient,
    ClaudeExamExtractionService,
    ExamExtractionRequest,
    ExtractedCoverSheet,
    ExtractedExceptionRow,
    ExtractedIndexEntry,
    ExtractedIndexSheet,
    ExtractedMortgageRow,
    ExtractedSheetRows,
    ExtractedTaxRow,
    IndexColumn,
    PageAssignment,
    PageClassification,
    SheetImage,
    classification_view,
    normalize_confidence,
    normalize_state,
    parse_money,
    parse_recording_ref,
    parse_sheet_date,
    reading_views,
)
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources.base import SourceResultStatus

ModelT = TypeVar("ModelT", bound=BaseModel)

FILE_NUMBER = "OH-00000-SAMPLE"
FAKE_API_KEY = "sk-ant-test-DO-NOT-LEAK-0123456789"

# Page images are opaque to these tests; only the page numbers matter.
PAGES = [
    SheetImage(page_number=n, data_base64="ZmFrZQ==")
    for n in (1, 11, 13, 15, 16, 19)
]

CLASSIFICATION = PageClassification(
    assignments=[
        PageAssignment(page_number=1, sheet=ExamSheetKind.SEARCH_COVER, confidence="high"),
        PageAssignment(page_number=11, sheet=ExamSheetKind.TAX, confidence="high"),
        PageAssignment(page_number=13, sheet=ExamSheetKind.TAX, confidence="high"),
        PageAssignment(page_number=15, sheet=ExamSheetKind.MORTGAGES, confidence="high"),
        PageAssignment(page_number=16, sheet=ExamSheetKind.EXCEPTIONS, confidence="high"),
        PageAssignment(page_number=19, sheet=ExamSheetKind.INDEX_SUMMARY, confidence="high"),
    ]
)

COVER = ExtractedCoverSheet(
    confidence="high",
    order_number=FILE_NUMBER,
    county="Example",
    state="oh",
    auditor_owners="Example, Alex Q & Jamie",
    buyers="Sample, Sam & Robin",
    property_line1="123 Example Road",
    property_city="Exampleville",
    property_postal_code="00000",
    search_start_date="1/1/1921",
    completed_date="9/1/26",
    lsot_book="0900",
    lsot_page="100",
    declared_mortgage_count=1,
    declared_judgment_count=0,
    declared_exception_count=2,
    matters_of_concern=["Possible outstanding life estate interest."],
)

MORTGAGE_ROWS = ExtractedSheetRows(
    mortgages=[
        ExtractedMortgageRow(
            confidence="high",
            src_text="OR 0311/415 1/15/10",
            book="0311",
            page="415",
            borrowers="Alex Q. Example and Jamie Example, husband and wife",
            lender="Example Savings Bank",
            amount="$100,000.00",
            executed_date="1/15/10",
            recorded_date="1/22/10",
            maturity_date="2/1/40",
        )
    ]
)

EXCEPTION_ROWS = ExtractedSheetRows(
    exceptions=[
        ExtractedExceptionRow(
            confidence="high",
            book="0931",
            page="104",
            instrument_kinds=["easement", "right_of_way", "not_a_real_kind"],
            first_party="Alex Q. and Jamie Example, h/w",
            second_party="Example Power Company",
            executed_date="3/3/99",
        ),
        ExtractedExceptionRow(
            confidence="high",
            book="0461",
            page="212",
            instrument_kinds=["easement", "right_of_way"],
            first_party="Alex Example and Pat Example, h/w",
            second_party="Example Gas Transmission Company",
            executed_date="6/1/55",
        ),
    ]
)

TAX_ROWS = ExtractedSheetRows(
    tax_parcels=[
        ExtractedTaxRow(
            confidence="high",
            src_page=11,
            parcel_id="25-0000.000",
            tax_year=2025,
            taxpayer_name="Example Alex and Jamie",
            first_half_amount="100.50",
            first_half_paid=True,
            second_half_amount="99.50",
            second_half_paid=True,
        ),
        ExtractedTaxRow(
            confidence="high",
            src_page=13,
            parcel_id="25-0000.001",
            tax_year=2025,
            taxpayer_name="Example Alex and Jamie",
            first_half_amount="1,234.56",
            first_half_paid=True,
            second_half_amount="1,200.44",
            second_half_paid=True,
            special_assessment_amount="$18.00",
            special_assessment_paid=True,
            special_assessment_label="SOLID WASTE",
            cauv=True,
        ),
    ]
)

INDEX = ExtractedIndexSheet(
    confidence="high",
    entries=[
        ExtractedIndexEntry(column=IndexColumn.MORTGAGES, text="0311/415"),
        ExtractedIndexEntry(column=IndexColumn.EASEMENTS_RIGHTS_OF_WAY, text="0461/212"),
        ExtractedIndexEntry(column=IndexColumn.EASEMENTS_RIGHTS_OF_WAY, text="0931/104"),
    ],
    name_searches=["Example Alex and Jamie"],
)


class FakeExtractionClient:
    """Scripted stand-in for the vision extractor. No network, no model."""

    def __init__(self, *, overrides: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.overrides = overrides or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def extract(
        self,
        *,
        instruction: str,
        images: list[SheetImage],
        schema: type[ModelT],
    ) -> ModelT:
        if self.fail:
            raise RuntimeError(f"upstream extractor exploded using key {FAKE_API_KEY}")

        self.calls.append((schema.__name__, instruction[:40]))

        if schema is PageClassification:
            return self.overrides.get("classification", CLASSIFICATION)
        if schema is ExtractedCoverSheet:
            return self.overrides.get("cover", COVER)
        if schema is ExtractedIndexSheet:
            return self.overrides.get("index", INDEX)
        if schema is ExtractedSheetRows:
            if "mortgage" in instruction:
                return self.overrides.get("mortgages", MORTGAGE_ROWS)
            if "exception" in instruction:
                return self.overrides.get("exceptions", EXCEPTION_ROWS)
            if "tax" in instruction:
                return self.overrides.get("tax", TAX_ROWS)
            return ExtractedSheetRows()
        raise AssertionError(f"unexpected schema {schema.__name__}")


class NormalizationTests(unittest.TestCase):
    def test_two_digit_years_resolve_against_a_pivot(self) -> None:
        today = date(2026, 9, 9)
        self.assertEqual(parse_sheet_date("1/15/10", today=today), date(2010, 1, 15))
        self.assertEqual(parse_sheet_date("6/1/55", today=today), date(1955, 6, 1))
        self.assertEqual(parse_sheet_date("3/3/99", today=today), date(1999, 3, 3))

    def test_maturity_dates_resolve_forward(self) -> None:
        today = date(2026, 9, 9)
        self.assertEqual(parse_sheet_date("2/1/40", today=today), date(1940, 2, 1))
        self.assertEqual(
            parse_sheet_date("2/1/40", prefer_future=True, today=today), date(2040, 2, 1)
        )

    def test_long_and_iso_dates_parse(self) -> None:
        self.assertEqual(parse_sheet_date("March 3, 1999"), date(1999, 3, 3))
        self.assertEqual(parse_sheet_date("1999-03-03"), date(1999, 3, 3))
        self.assertIsNone(parse_sheet_date("not a date"))
        self.assertIsNone(parse_sheet_date(None))

    def test_money_strips_symbols_and_separators(self) -> None:
        self.assertEqual(parse_money("$100,000.00"), Decimal("100000.00"))
        self.assertEqual(parse_money("1,234.56"), Decimal("1234.56"))
        self.assertIsNone(parse_money("  "))
        self.assertIsNone(parse_money("n/a"))

    def test_unknown_confidence_fails_safe_to_low(self) -> None:
        self.assertEqual(normalize_confidence("HIGH"), ExtractionConfidence.HIGH)
        self.assertEqual(normalize_confidence("medium"), ExtractionConfidence.MEDIUM)
        self.assertEqual(normalize_confidence("pretty sure"), ExtractionConfidence.LOW)
        self.assertEqual(normalize_confidence(None), ExtractionConfidence.LOW)

    def test_index_reference_parsing(self) -> None:
        ref = parse_recording_ref(" 0311 / 415 ")
        assert ref is not None
        self.assertEqual((ref.book, ref.page), ("0311", "415"))
        # Notes around a reference are ignored; the first reference is the entry.
        noted = parse_recording_ref("209/602 R")
        assert noted is not None
        self.assertEqual((noted.book, noted.page), ("209", "602"))
        labelled = parse_recording_ref("R/W: 1111/576 (P)")
        assert labelled is not None
        self.assertEqual((labelled.book, labelled.page), ("1111", "576"))
        released = parse_recording_ref("1222/1265 R.333/752")
        assert released is not None
        self.assertEqual((released.book, released.page), ("1222", "1265"))
        self.assertIsNone(parse_recording_ref(None))

    def test_index_reference_keeps_a_record_series_prefix(self) -> None:
        ref = parse_recording_ref("DV 212/58")
        assert ref is not None
        self.assertEqual((ref.book, ref.page, ref.document_type), ("212", "58", "DV"))
        plat = parse_recording_ref("6-B/140")
        assert plat is not None
        self.assertEqual((plat.book, plat.page, plat.document_type), ("6-B", "140", None))
        # A case number is not a book/page reference.
        self.assertIsNone(parse_recording_ref("18 JL 2207"))

    def test_state_names_normalize_to_codes(self) -> None:
        self.assertEqual(normalize_state("West Virginia"), "WV")
        self.assertEqual(normalize_state(" ohio "), "OH")
        self.assertEqual(normalize_state("Ky"), "KY")
        self.assertEqual(normalize_state("W. Virginia"), None)
        self.assertIsNone(normalize_state("Narnia"))
        self.assertIsNone(normalize_state(None))


def _png(width: int, height: int) -> str:
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class ImageViewTests(unittest.TestCase):
    def test_reading_tiles_cover_the_page_unscaled(self) -> None:
        import base64
        import io

        from PIL import Image

        # A letter page at 300 dpi: 2550 x 3300.
        page = SheetImage(page_number=16, data_base64=_png(2550, 3300))
        views = reading_views(page)
        self.assertEqual(views[0].view, "full page")
        self.assertEqual(len(views), 1 + 2 * 3)
        self.assertEqual(views[1].label, "Page 16 (zoomed tile, row 1 of 3, column 1 of 2)")
        self.assertTrue(all(v.page_number == 16 for v in views))
        for tile in views[1:]:
            with Image.open(io.BytesIO(base64.b64decode(tile.data_base64))) as img:
                self.assertLessEqual(max(img.size), 1568)

    def test_small_pages_are_not_tiled(self) -> None:
        page = SheetImage(page_number=2, data_base64=_png(850, 1100))
        self.assertEqual([v.view for v in reading_views(page)], ["full page"])

    def test_undecodable_images_pass_through(self) -> None:
        page = SheetImage(page_number=3, data_base64="ZmFrZQ==")
        self.assertEqual(reading_views(page), [page])
        self.assertIs(classification_view(page), page)

    def test_classification_view_shrinks_large_pages(self) -> None:
        import base64
        import io

        from PIL import Image

        page = SheetImage(page_number=1, data_base64=_png(1700, 2200))
        small = classification_view(page)
        with Image.open(io.BytesIO(base64.b64decode(small.data_base64))) as img:
            self.assertLessEqual(max(img.size), 1000)


class ExtractionServiceTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, **kwargs: Any) -> ClaudeExamExtractionService:
        return ClaudeExamExtractionService(
            settings=TitleMCPSettings(anthropic_api_key=FAKE_API_KEY),
            client=FakeExtractionClient(**kwargs),
        )

    def _request(self) -> ExamExtractionRequest:
        return ExamExtractionRequest(file_number=FILE_NUMBER, pages=list(PAGES))

    async def test_missing_credentials_requires_configuration(self) -> None:
        service = ClaudeExamExtractionService(
            settings=TitleMCPSettings(anthropic_api_key=None), client=None
        )
        result = await service.extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertIsNone(result.package)
        self.assertTrue(result.warnings)
        self.assertIn("TITLE_MCP_ANTHROPIC_API_KEY", result.warnings[0])

    async def test_no_pages_returns_no_results(self) -> None:
        service = self._service()
        result = await service.extract_package(
            ExamExtractionRequest(file_number=FILE_NUMBER, pages=[])
        )
        self.assertEqual(result.status, SourceResultStatus.NO_RESULTS)

    async def test_client_failure_is_reported_not_raised(self) -> None:
        service = self._service(fail=True)
        result = await service.extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.FAILED)
        self.assertIsNone(result.package)
        self.assertEqual(result.warnings, ["Extraction failed: RuntimeError"])

    async def test_credentials_never_surface_in_the_result(self) -> None:
        service = self._service(fail=True)
        result = await service.extract_package(self._request())

        payload = result.model_dump_json()
        self.assertNotIn(FAKE_API_KEY, payload)
        self.assertNotIn("sk-ant", payload)

    async def test_missing_cover_sheet_returns_partial(self) -> None:
        service = self._service(
            overrides={
                "classification": PageClassification(
                    assignments=[
                        PageAssignment(page_number=15, sheet=ExamSheetKind.MORTGAGES),
                    ]
                )
            }
        )
        result = await service.extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.PARTIAL)
        self.assertIsNone(result.package)
        self.assertIn("cover sheet", result.warnings[0])

    async def test_canonical_mapping_produces_an_exam_package(self) -> None:
        service = self._service()
        result = await service.extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        package = result.package
        assert package is not None

        self.assertEqual(package.schema_name, "title_mcp.exam_package")
        self.assertEqual(package.record_type, "exam_package")
        self.assertTrue(package.requires_human_review)
        self.assertEqual(package.source["provider"], "anthropic")

        self.assertEqual(package.cover.state, "OH")
        self.assertEqual(package.cover.completed_date, date(2026, 9, 1))
        self.assertEqual(package.cover.declared_exception_count, 2)

        mortgage = package.mortgages[0]
        self.assertEqual(mortgage.original_amount, Decimal("100000.00"))
        self.assertEqual(mortgage.executed_date, date(2010, 1, 15))
        self.assertEqual(mortgage.maturity_date, date(2040, 2, 1))
        self.assertEqual(mortgage.provenance.sheet, ExamSheetKind.MORTGAGES)
        self.assertEqual(mortgage.provenance.src_page, 15)
        self.assertEqual(mortgage.provenance.confidence, ExtractionConfidence.HIGH)

        self.assertEqual([p.provenance.src_page for p in package.tax_parcels], [11, 13])
        self.assertEqual(package.tax_parcels[1].special_assessment_amount, Decimal("18.00"))

        self.assertEqual(len(package.exceptions[0].instrument_kinds), 2)
        self.assertEqual(package.exceptions[1].executed_date, date(1955, 6, 1))

        assert package.index is not None
        self.assertEqual(len(package.index.easements_rights_of_way), 2)

    async def test_missing_index_page_warns_but_still_extracts(self) -> None:
        service = self._service(
            overrides={
                "classification": PageClassification(
                    assignments=[
                        a for a in CLASSIFICATION.assignments
                        if a.sheet is not ExamSheetKind.INDEX_SUMMARY
                    ]
                )
            }
        )
        result = await service.extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        assert result.package is not None
        self.assertIsNone(result.package.index)
        self.assertIn("cross-reference checks were skipped", result.warnings[0])

    async def test_extracted_package_reconciles_green_and_renders(self) -> None:
        """The whole chain: extract, reconcile, render -- with no live model."""

        service = self._service()
        result = await service.extract_package(self._request())
        assert result.package is not None

        reconciliation = ExamReconciliationService().reconcile(result.package)
        self.assertEqual(reconciliation.status, ReconciliationStatus.GREEN)

        rendered = CommitmentRenderService().render(
            package=result.package,
            reconciliation=reconciliation,
            clause_set=ohio_default_clause_set(),
        )
        self.assertEqual(rendered.status, CommitmentRenderStatus.RENDERED)
        assert rendered.draft is not None
        self.assertEqual(len(rendered.draft.schedule_b1), 10)
        self.assertEqual(len(rendered.draft.schedule_b2), 15)
        self.assertEqual(
            rendered.draft.schedule_b1[-1].text,
            "Mortgage from Alex Q. Example and Jamie Example, husband and wife, "
            "to Example Savings Bank, in the amount of $100,000.00, dated "
            "January 15, 2010, as recorded in Official Record 0311, Page 415.",
        )

    async def test_struck_index_entries_are_dropped_only_with_evidence(self) -> None:
        E = IndexColumn.EASEMENTS_RIGHTS_OF_WAY
        index = INDEX.model_copy(
            update={
                "entries": [
                    *INDEX.entries,
                    ExtractedIndexEntry(
                        column=IndexColumn.MORTGAGES, text="0198/220", struck=True,
                        strike_evidence="hand-drawn line through the entry", annotation="rel",
                    ),
                    ExtractedIndexEntry(column=E, text="0455/10", struck=True),
                ]
            }
        )
        result = await self._service(overrides={"index": index}).extract_package(self._request())

        assert result.package is not None and result.package.index is not None
        mortgages = [r.display for r in result.package.index.mortgages]
        easements = [r.display for r in result.package.index.easements_rights_of_way]
        self.assertNotIn("0198/220", mortgages)
        self.assertIn("0455/10", easements)
        self.assertEqual(
            [e["text"] for e in result.source_specific["index_struck_entries"]], ["0198/220"]
        )
        self.assertTrue(any("0455/10" in w and "kept as live" in w for w in result.warnings))

    async def test_an_assessment_amount_reported_as_a_label_is_the_amount(self) -> None:
        rows = TAX_ROWS.model_copy(deep=True)
        rows.tax_parcels[0].special_assessment_amount = None
        rows.tax_parcels[0].special_assessment_label = "$18"
        result = await self._service(overrides={"tax": rows}).extract_package(self._request())

        assert result.package is not None
        parcel = result.package.tax_parcels[0]
        self.assertEqual(parcel.special_assessment_amount, Decimal("18"))
        self.assertIsNone(parcel.special_assessment_label)

    async def test_two_digit_tax_year_is_expanded(self) -> None:
        rows = TAX_ROWS.model_copy(deep=True)
        rows.tax_parcels[0].tax_year = 25
        result = await self._service(overrides={"tax": rows}).extract_package(self._request())

        assert result.package is not None
        self.assertEqual(result.package.tax_parcels[0].tax_year, 2025)

    async def test_an_unbuildable_row_is_reported_not_fatal(self) -> None:
        rows = TAX_ROWS.model_copy(deep=True)
        rows.tax_parcels[0].tax_year = 1776
        result = await self._service(overrides={"tax": rows}).extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        assert result.package is not None
        self.assertEqual(len(result.package.tax_parcels), len(TAX_ROWS.tax_parcels) - 1)
        self.assertTrue(any("tax row" in w and "tax_year" in w for w in result.warnings))

    async def test_a_ticked_entry_reported_struck_stays_live(self) -> None:
        E = IndexColumn.EASEMENTS_RIGHTS_OF_WAY
        index = INDEX.model_copy(
            update={
                "entries": [
                    ExtractedIndexEntry(column=IndexColumn.MORTGAGES, text="0311/415"),
                    ExtractedIndexEntry(
                        column=E, text="DV 0461/212", struck=True, annotation="check mark",
                        strike_evidence="stroke through the leading letters",
                    ),
                    ExtractedIndexEntry(column=E, text="0931/104", annotation="✓"),
                ]
            }
        )
        result = await self._service(overrides={"index": index}).extract_package(self._request())

        assert result.package is not None
        rec = ExamReconciliationService().reconcile(result.package)
        self.assertEqual(rec.status, ReconciliationStatus.GREEN, rec.blocking)
        self.assertTrue(any("ticked" in w for w in result.warnings))

    async def test_released_mortgages_are_set_aside(self) -> None:
        index = INDEX.model_copy(
            update={
                "entries": [
                    *INDEX.entries,
                    ExtractedIndexEntry(
                        column=IndexColumn.MORTGAGES, text="0187/1265", annotation="R. 0290/752",
                        released=True,
                    ),
                ]
            }
        )
        result = await self._service(overrides={"index": index}).extract_package(self._request())

        assert result.package is not None and result.package.index is not None
        self.assertNotIn("0187/1265", [r.display for r in result.package.index.mortgages])
        struck = result.source_specific["index_struck_entries"]
        self.assertEqual(
            [(e["text"], e["evidence"]) for e in struck], [("0187/1265", "release noted")]
        )

    async def test_index_entries_that_are_not_references_are_reported(self) -> None:
        index = INDEX.model_copy(
            update={
                "entries": [
                    *INDEX.entries,
                    ExtractedIndexEntry(column=IndexColumn.MORTGAGES, text="18 JL 2207"),
                ]
            }
        )
        result = await self._service(overrides={"index": index}).extract_package(self._request())

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(any("18 JL 2207" in w for w in result.warnings))

    async def test_prefixed_index_reference_matches_the_detail_sheet(self) -> None:
        E = IndexColumn.EASEMENTS_RIGHTS_OF_WAY
        index = INDEX.model_copy(
            update={
                "entries": [
                    ExtractedIndexEntry(column=IndexColumn.MORTGAGES, text="OR 0311/415"),
                    ExtractedIndexEntry(column=E, text="DV 0461/212"),
                    ExtractedIndexEntry(column=E, text="0931/104"),
                ]
            }
        )
        result = await self._service(overrides={"index": index}).extract_package(self._request())

        assert result.package is not None
        rec = ExamReconciliationService().reconcile(result.package)
        self.assertEqual(rec.status, ReconciliationStatus.GREEN, rec.blocking)

    async def test_spelled_out_state_is_normalized(self) -> None:
        cover = COVER.model_copy(update={"state": "West Virginia"})
        result = await self._service(overrides={"cover": cover}).extract_package(self._request())

        assert result.package is not None
        self.assertEqual(result.package.cover.state, "WV")

    async def test_unreadable_row_blocks_the_commitment(self) -> None:
        """An extractor that is unsure cannot produce a commitment."""

        unsure = ExtractedSheetRows(
            mortgages=[
                ExtractedMortgageRow(
                    confidence="not sure at all",
                    book="0311",
                    page="415",
                    borrowers="A???x Q. Example",
                    lender="Example Savings Bank",
                    amount="$100,000.00",
                    executed_date="1/15/10",
                )
            ]
        )
        service = self._service(overrides={"mortgages": unsure})
        result = await service.extract_package(self._request())
        assert result.package is not None

        self.assertEqual(
            result.package.mortgages[0].provenance.confidence, ExtractionConfidence.LOW
        )

        reconciliation = ExamReconciliationService().reconcile(result.package)
        self.assertEqual(reconciliation.status, ReconciliationStatus.RED)

        rendered = CommitmentRenderService().render(
            package=result.package,
            reconciliation=reconciliation,
            clause_set=ohio_default_clause_set(),
        )
        self.assertEqual(rendered.status, CommitmentRenderStatus.REFUSED)
        self.assertIsNone(rendered.draft)


class _RecordingMessages:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return type("Response", (), {"parsed_output": self.parsed})()


class _RecordingAnthropic:
    def __init__(self, parsed: Any) -> None:
        self.messages = _RecordingMessages(parsed)


class ClaudeClientRequestShapeTests(unittest.TestCase):
    """Verifies the request we build, without touching the network."""

    def _client(self, parsed: Any) -> tuple[ClaudeExamExtractionClient, _RecordingAnthropic]:
        fake = _RecordingAnthropic(parsed)
        return (
            ClaudeExamExtractionClient(api_key=FAKE_API_KEY, client=fake),
            fake,
        )

    def test_builds_a_cached_system_prompt_and_image_blocks(self) -> None:
        client, fake = self._client(INDEX)

        returned = client.extract(
            instruction="Transcribe the index page.",
            images=[SheetImage(page_number=19, data_base64="ZmFrZQ==")],
            schema=ExtractedIndexSheet,
        )

        self.assertIs(returned, INDEX)
        kwargs = fake.messages.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5")
        self.assertIs(kwargs["output_format"], ExtractedIndexSheet)

        system = kwargs["system"][0]
        self.assertEqual(system["cache_control"], {"type": "ephemeral"})
        self.assertIn("Transcribe only what is written", system["text"])

        content = kwargs["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "Page 19:"})
        self.assertEqual(content[1]["type"], "image")
        self.assertEqual(content[1]["source"]["media_type"], "image/png")
        self.assertEqual(content[1]["source"]["data"], "ZmFrZQ==")
        self.assertEqual(content[-1]["type"], "text")
        self.assertIn("index page", content[-1]["text"])

    def test_unparsable_response_raises_for_the_service_to_catch(self) -> None:
        client, _ = self._client(None)

        with self.assertRaises(ValueError):
            client.extract(
                instruction="anything",
                images=[SheetImage(page_number=1, data_base64="ZmFrZQ==")],
                schema=ExtractedIndexSheet,
            )


if __name__ == "__main__":
    unittest.main()

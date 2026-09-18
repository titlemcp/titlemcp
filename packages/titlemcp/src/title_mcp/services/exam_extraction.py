from __future__ import annotations

import asyncio
import base64
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from title_mcp.observability import get_logger
from title_mcp.services.document_analysis import (
    DocumentAnalysisRequest,
    DocumentAnalysisResult,
    DocumentAnalysisService,
)
from title_mcp.settings import TitleMCPSettings, get_settings
from title_mcp.sources.base import SourceResultStatus

LOGGER = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_ABBREVIATIONS: dict[str, str] = {
    "SAD": "Same As Deed (the grantees named on the vesting deed)",
    "LSOT": "Last Shown Owner Transfer",
    "h/w": "husband and wife",
    "w/h": "husband and wife",
    "dec'd": "deceased",
    "COT": "Certificate of Transfer",
    "DV": "Deed Volume",
    "OR": "Official Record",
    "MV": "Mortgage Volume",
    "L/E": "life estate",
    "JTWROS": "joint tenants with right of survivorship",
    "R": "Released (struck through on the index means satisfied of record)",
}


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------

_DATE_PATTERNS = ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y")


def normalize_confidence(raw: str | None) -> ExtractionConfidence:
    """Map a model-supplied confidence onto the enum, failing safe to LOW.

    Anything unrecognized becomes LOW, which blocks reconciliation. An extractor
    that reports confidence in an unexpected vocabulary must not be able to talk
    its way onto a commitment.
    """

    if raw is None:
        return ExtractionConfidence.LOW
    try:
        return ExtractionConfidence(raw.strip().lower())
    except ValueError:
        return ExtractionConfidence.LOW


def parse_sheet_date(
    raw: str | None,
    *,
    prefer_future: bool = False,
    today: date | None = None,
) -> date | None:
    """Parse a date as an abstractor hand-writes it.

    Two-digit years are resolved against a pivot: ``7/18/56`` is 1956, ``4/20/09``
    is 2009. ``prefer_future`` handles fields that must be forward-looking, such as
    a mortgage maturity date, where ``5/1/39`` means 2039 rather than 1939.
    """

    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    reference = today or date.today()

    short = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2})", text)
    if short:
        month, day, year_suffix = (int(part) for part in short.groups())
        century = 2000 if year_suffix <= reference.year % 100 else 1900
        try:
            parsed = date(century + year_suffix, month, day)
        except ValueError:
            return None
        if prefer_future and parsed < reference:
            try:
                parsed = parsed.replace(year=parsed.year + 100)
            except ValueError:
                return None
        return parsed

    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_money(raw: str | None) -> Decimal | None:
    """Parse a currency amount written with or without separators and symbols."""

    if raw is None:
        return None
    text = re.sub(r"[^0-9.\-]", "", raw.strip())
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_bool(raw: bool | str | None) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return raw.strip().lower() in {"y", "yes", "true", "x", "1"}


# --------------------------------------------------------------------------
# What the extractor is asked to return, per sheet
# --------------------------------------------------------------------------


US_STATE_CODES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def normalize_state(raw: str | None) -> str | None:
    """Two-letter code for a state as written on a sheet, or None if unrecognized.

    Cover sheets spell the state out ("West Virginia") as often as they abbreviate it.
    """

    if raw is None:
        return None
    text = re.sub(r"[^a-z ]", "", raw.strip().lower()).strip()
    if len(text) == 2 and text.upper() in US_STATE_CODES.values():
        return text.upper()
    return US_STATE_CODES.get(re.sub(r"\s+", " ", text))


class SheetImage(BaseModel):
    """One rendered page of a scanned exam package, or a zoomed view of one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page_number: int = Field(ge=1)
    media_type: str = "image/png"
    data_base64: str = Field(min_length=1)
    view: str | None = None

    @property
    def label(self) -> str:
        return f"Page {self.page_number}" + (f" ({self.view})" if self.view else "")


# Longest edge, in pixels, for the page images used only to classify sheets.
CLASSIFICATION_MAX_EDGE = 1000
# Models shrink any image whose long edge exceeds this, and shrinking is where
# handwritten digits get misread. Reading tiles are cut to fit within it.
MAX_TILE_EDGE = 1568
# Share of each tile that overlaps its neighbour, so a row or field cut by one
# tile edge appears whole in the next.
TILE_OVERLAP = 0.12


def _load_image(image: SheetImage) -> Any | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        return Image.open(io.BytesIO(base64.b64decode(image.data_base64))).convert("RGB")
    except Exception:  # noqa: BLE001 - an undecodable image is passed through untouched
        return None


def _encode(img: Any, like: SheetImage, view: str | None) -> SheetImage:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return SheetImage(
        page_number=like.page_number,
        media_type="image/jpeg",
        data_base64=base64.b64encode(buffer.getvalue()).decode(),
        view=view,
    )


def classification_view(image: SheetImage, max_edge: int = CLASSIFICATION_MAX_EDGE) -> SheetImage:
    """A reduced copy for page classification, which needs layout, not handwriting."""

    img = _load_image(image)
    if img is None or max(img.size) <= max_edge:
        return image
    img.thumbnail((max_edge, max_edge))
    return _encode(img, image, image.view)


def _spans(length: int, tile: int) -> list[tuple[int, int]]:
    """Overlapping [start, end) spans of at most ``tile`` covering ``length``."""

    if length <= tile:
        return [(0, length)]
    step = int(tile * (1 - TILE_OVERLAP))
    count = -(-(length - tile) // step) + 1
    stride = (length - tile) / (count - 1)
    return [(round(i * stride), round(i * stride) + tile) for i in range(count)]


def reading_views(image: SheetImage, max_edge: int = MAX_TILE_EDGE) -> list[SheetImage]:
    """The full page plus overlapping tiles that each arrive at full resolution.

    A model shrinks a whole page to fit its image limit, and at that scale one
    abstractor's looped 2 reads as a 0 and a 1 run into a divider reads as a 3.
    Measured on a real package, the same entries read correctly from an unscaled
    crop and wrongly from a half-page view. Each tile here fits within
    ``max_edge``, so none is shrunk. Supply pages at about 300 dpi. Without
    Pillow, or for an image that cannot be decoded, the page is sent as it is.
    """

    img = _load_image(image)
    if img is None:
        return [image]
    width, height = img.size
    if max(width, height) <= max_edge:
        return [image.model_copy(update={"view": "full page"})]
    rows, cols = _spans(height, max_edge), _spans(width, max_edge)
    # The model would shrink the full page anyway; shrinking it here keeps the request small.
    overview = img.copy()
    overview.thumbnail((max_edge, max_edge))
    views = [_encode(overview, image, "full page")]
    for r, (top, bottom) in enumerate(rows, start=1):
        for c, (left, right) in enumerate(cols, start=1):
            views.append(
                _encode(
                    img.crop((left, top, right, bottom)),
                    image,
                    f"zoomed tile, row {r} of {len(rows)}, column {c} of {len(cols)}",
                )
            )
    return views


def _with_reading_views(images: list[SheetImage]) -> list[SheetImage]:
    return [view for image in images for view in reading_views(image)]


class ExtractedRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    confidence: str | None = None
    src_text: str | None = None
    src_page: int | None = None


class ExtractedMortgageRow(ExtractedRow):
    book: str | None = None
    page: str | None = None
    borrowers: str | None = None
    lender: str | None = None
    amount: str | None = None
    executed_date: str | None = None
    recorded_date: str | None = None
    maturity_date: str | None = None
    prior_owner: bool = False
    heloc: bool = False
    notes: str | None = None


class ExtractedExceptionRow(ExtractedRow):
    book: str | None = None
    page: str | None = None
    record_series: str | None = Field(
        default=None,
        description="The record series ticked or written, e.g. 'OR', 'DV', 'Plat Book'.",
    )
    instrument_kinds: list[str] = Field(
        default_factory=list,
        description="Any of: easement, right_of_way, lease, agreement, restriction, plat.",
    )
    first_party: str | None = None
    second_party: str | None = None
    executed_date: str | None = None
    instrument_name: str | None = None
    notes: str | None = None


class ExtractedJudgmentRow(ExtractedRow):
    debtor: str | None = None
    creditor: str | None = None
    case_number: str | None = None
    court: str | None = None
    amount: str | None = None
    book: str | None = None
    page: str | None = None


class ExtractedTaxRow(ExtractedRow):
    parcel_id: str | None = None
    tax_year: int | None = None
    taxpayer_name: str | None = None
    first_half_amount: str | None = None
    first_half_paid: bool = False
    second_half_amount: str | None = None
    second_half_paid: bool = False
    special_assessment_amount: str | None = Field(
        default=None,
        description=(
            "Only when an assessment box is ticked, not struck through. A struck "
            "assessment does not apply to the parcel."
        ),
    )
    special_assessment_paid: bool = False
    special_assessment_label: str | None = Field(
        default=None, description="What the assessment is for, e.g. 'SOLID WASTE'."
    )
    cauv: bool = False


class ExtractedCoverSheet(ExtractedRow):
    order_number: str | None = None
    county: str | None = None
    state: str | None = None
    auditor_owners: str | None = None
    buyers: str | None = None
    property_line1: str | None = None
    property_city: str | None = None
    property_postal_code: str | None = None
    search_start_date: str | None = None
    completed_date: str | None = None
    completed_by: str | None = None
    lsot_book: str | None = None
    lsot_page: str | None = None
    declared_mortgage_count: int | None = Field(
        default=None,
        description=(
            "The count written in the form's mortgage-count box; null if the form has none."
        ),
    )
    declared_judgment_count: int | None = Field(
        default=None,
        description=(
            "The count written in the form's judgment-count box; null if the form has none."
        ),
    )
    declared_exception_count: int | None = Field(
        default=None,
        description=(
            "The count written in the form's exception-count box; null if the form has none."
        ),
    )
    matters_of_concern: list[str] = Field(default_factory=list)


class IndexColumn(StrEnum):
    MORTGAGES = "mortgages"
    LEASES_AGREEMENTS = "leases_agreements"
    EASEMENTS_RIGHTS_OF_WAY = "easements_rights_of_way"


class ExtractedIndexEntry(ExtractedRow):
    """One reference written in a column of the index page.

    Struck entries are reported, not omitted, so the decision to drop one is made
    in code and is visible in the result rather than lost inside the model.
    """

    column: IndexColumn
    text: str = Field(
        description=(
            "The reference only, as written, e.g. 'DV 212/58' or '733/19'. Labels such "
            "as 'R/W:' or 'Agmt:', release references, and notes go in annotation."
        )
    )
    struck: bool = False
    strike_evidence: str | None = Field(
        default=None,
        description="Required when struck: what shows it is struck, not merely written on a rule.",
    )
    annotation: str | None = Field(
        default=None, description="Any note beside the entry, e.g. 'rel', 'NOP', a check mark."
    )
    released: bool = Field(
        default=False,
        description=(
            "True when a release is noted beside a mortgage, e.g. 'rel' or a release "
            "reference such as 'R. 328/752', whether or not the entry is struck."
        ),
    )


class ExtractedIndexSheet(ExtractedRow):
    entries: list[ExtractedIndexEntry] = Field(default_factory=list)
    name_searches: list[str] = Field(default_factory=list)


class ExtractedSheetRows(BaseModel):
    """Container the extractor fills for one detail sheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mortgages: list[ExtractedMortgageRow] = Field(default_factory=list)
    exceptions: list[ExtractedExceptionRow] = Field(default_factory=list)
    judgments: list[ExtractedJudgmentRow] = Field(default_factory=list)
    tax_parcels: list[ExtractedTaxRow] = Field(default_factory=list)


class PageAssignment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    page_number: int = Field(ge=1)
    sheet: ExamSheetKind | None = None
    confidence: str | None = None


class PageClassification(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    assignments: list[PageAssignment] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Client contract
# --------------------------------------------------------------------------


class ExamExtractionClient(Protocol):
    """Vision extraction behind a schema.

    Implementations are injected so the service is testable without a network or
    a model provider.
    """

    def extract(
        self,
        *,
        instruction: str,
        images: list[SheetImage],
        schema: type[ModelT],
    ) -> ModelT:
        """Return an instance of ``schema`` read from the supplied page images."""


class ExamExtractionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_number: str = Field(min_length=1)
    document_uri: str | None = None
    pages: list[SheetImage] = Field(default_factory=list)
    abbreviations: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ABBREVIATIONS))


class ExamExtractionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.exam_extraction"
    schema_version: str = "1.0"
    record_type: str = "exam_extraction"
    file_number: str
    status: SourceResultStatus
    package: ExamPackage | None = None
    warnings: list[str] = Field(default_factory=list)
    page_assignments: list[PageAssignment] = Field(default_factory=list)
    requires_human_review: bool = True
    source_specific: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Claude client
# --------------------------------------------------------------------------


class ClaudeExamExtractionClient:
    """Schema-constrained vision extraction using the Anthropic Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-opus-5",
        max_tokens: int = 16000,
        timeout_seconds: float = 300.0,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key, timeout=self._timeout_seconds)
        return self._client

    def extract(
        self,
        *,
        instruction: str,
        images: list[SheetImage],
        schema: type[ModelT],
    ) -> ModelT:
        content: list[dict[str, Any]] = []
        for image in images:
            # Without a label the model can only infer page numbers from order.
            content.append({"type": "text", "text": f"{image.label}:"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data_base64,
                    },
                }
            )
        content.append({"type": "text", "text": instruction})

        response = self._resolve_client().messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": EXTRACTION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(f"Extractor returned no parsable {schema.__name__}")
        return parsed


EXTRACTION_SYSTEM_PROMPT = """\
You read scanned title abstract summary sheets and transcribe what is written on \
them. These are pre-printed forms completed by hand by a title abstractor.

Rules:

1. Transcribe only what is written on the sheet in front of you. Never infer a \
matter from an underlying recorded document, and never add an item the abstractor \
did not write down. A blank line is a blank line.
2. Struck-through entries are satisfied or superseded. These forms are ruled, and \
the abstractor writes on the printed lines, so a printed rule often runs through the \
lower part of the handwriting. That is not a strike. An entry is struck only when a \
separate hand-drawn stroke crosses it, in the writer's ink, usually through the middle \
of the characters and past their ends, often with a note such as "rel" or "NOP". A \
check mark beside an entry means it was carried to a detail sheet, not that it was \
struck. When you cannot tell, the entry is not struck.
3. Report a confidence of "high" only when the handwriting is unambiguous and every \
field you report is legible. Use "medium" when you are reading a plausible but \
uncertain character, and "low" when any part is a guess. Low confidence is routed \
to a human, so it is always safe to use.
4. Copy dates and amounts exactly as written, including the abstractor's own \
formatting. Do not reformat, expand, or interpret them.
5. Put the verbatim text you read for each row in src_text so a reviewer can check \
it against the scan.
6. Some pages come with zoomed tiles after the full page. Read handwriting from \
the tiles and use the full page only for layout. Tiles overlap, so the same row can \
appear in two of them: report each row once, with the page number of the page it \
is on.
"""


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


class ClaudeExamExtractionService(DocumentAnalysisService):
    """Fills the document-analysis placeholder for handwritten exam packages.

    The service converts extracted rows into domain records and attaches
    provenance; it makes no title determinations. Everything it produces is
    reconciled before it can reach a commitment.
    """

    def __init__(
        self,
        *,
        settings: TitleMCPSettings | None = None,
        client: ExamExtractionClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    # -- generic DocumentAnalysisService contract --------------------------

    async def analyze(self, request: DocumentAnalysisRequest) -> DocumentAnalysisResult:
        client = self._resolve_client()
        if client is None:
            return DocumentAnalysisResult(
                provider="anthropic",
                document_uri=request.document_uri,
                fields={"status": SourceResultStatus.REQUIRES_CONFIGURATION.value},
                requires_review=True,
            )
        return DocumentAnalysisResult(
            provider="anthropic",
            document_uri=request.document_uri,
            fields={
                "status": SourceResultStatus.SUCCEEDED.value,
                "note": "Use extract_package for exam packages.",
            },
            requires_review=True,
        )

    # -- exam-package extraction -------------------------------------------

    async def extract_package(self, request: ExamExtractionRequest) -> ExamExtractionResult:
        client = self._resolve_client()
        if client is None:
            return ExamExtractionResult(
                file_number=request.file_number,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    "Anthropic credentials are not configured. Set "
                    "TITLE_MCP_ANTHROPIC_API_KEY to enable exam extraction."
                ],
            )

        if not request.pages:
            return ExamExtractionResult(
                file_number=request.file_number,
                status=SourceResultStatus.NO_RESULTS,
                warnings=["No page images were supplied."],
            )

        try:
            return await asyncio.to_thread(self._extract_sync, client, request)
        except Exception as exc:  # noqa: BLE001 - connectors report, never raise
            LOGGER.warning(
                "exam_extraction.failed",
                extra={"file_number": request.file_number, "error_type": type(exc).__name__},
            )
            return ExamExtractionResult(
                file_number=request.file_number,
                status=SourceResultStatus.FAILED,
                warnings=[f"Extraction failed: {type(exc).__name__}"],
            )

    def _resolve_client(self) -> ExamExtractionClient | None:
        if self._client is not None:
            return self._client
        api_key = getattr(self._settings, "anthropic_api_key", None)
        if not api_key:
            return None
        self._client = ClaudeExamExtractionClient(
            api_key=api_key,
            model=getattr(self._settings, "anthropic_model", "claude-opus-5"),
        )
        return self._client

    def _extract_sync(
        self,
        client: ExamExtractionClient,
        request: ExamExtractionRequest,
    ) -> ExamExtractionResult:
        lexicon = "\n".join(f"  {k} = {v}" for k, v in sorted(request.abbreviations.items()))
        preamble = f"Abbreviations used on these sheets:\n{lexicon}\n\n"

        classification = client.extract(
            instruction=(
                f"{preamble}Identify which summary sheet each page is. Pages that are "
                "recorded documents, county printouts, or maps have no sheet type."
            ),
            images=[classification_view(page) for page in request.pages],
            schema=PageClassification,
        )

        by_page = {image.page_number: image for image in request.pages}
        grouped: dict[ExamSheetKind, list[SheetImage]] = {}
        for assignment in classification.assignments:
            if assignment.sheet is None:
                continue
            image = by_page.get(assignment.page_number)
            if image is not None:
                grouped.setdefault(assignment.sheet, []).append(image)

        warnings: list[str] = []
        source_specific: dict[str, Any] = {}
        cover_pages = grouped.get(ExamSheetKind.SEARCH_COVER)
        if not cover_pages:
            return ExamExtractionResult(
                file_number=request.file_number,
                status=SourceResultStatus.PARTIAL,
                warnings=["No search cover sheet was found; the package cannot be reconciled."],
                page_assignments=classification.assignments,
            )

        cover_raw = client.extract(
            instruction=f"{preamble}Transcribe the search cover sheet.",
            images=_with_reading_views(cover_pages),
            schema=ExtractedCoverSheet,
        )
        cover = self._build_cover(cover_raw, cover_pages[0].page_number, request.file_number)
        if cover_raw.state and cover.state is None:
            warnings.append(
                f"Cover sheet state {cover_raw.state!r} is not a recognized US state; left blank."
            )

        mortgages: list[MortgageEntry] = []
        exceptions: list[ExceptionEntry] = []
        judgments: list[JudgmentEntry] = []
        tax_parcels: list[TaxParcelEntry] = []

        detail_sheets = (
            (ExamSheetKind.MORTGAGES, "Transcribe every mortgage row that is filled in."),
            (ExamSheetKind.EXCEPTIONS, "Transcribe every exception row that is filled in."),
            (ExamSheetKind.JUDGMENTS, "Transcribe every judgment-lien row that is filled in."),
            (ExamSheetKind.TAX, "Transcribe the tax status for each parcel shown."),
        )
        for kind, task in detail_sheets:
            pages = grouped.get(kind)
            if not pages:
                continue
            rows = client.extract(
                instruction=f"{preamble}{task}",
                images=_with_reading_views(pages),
                schema=ExtractedSheetRows,
            )
            page_number = pages[0].page_number
            for target, builder, found in (
                (mortgages, self._build_mortgage, rows.mortgages),
                (exceptions, self._build_exception, rows.exceptions),
                (judgments, self._build_judgment, rows.judgments),
                (tax_parcels, self._build_tax, rows.tax_parcels),
            ):
                for raw_row in found:
                    built = self._build_row(builder, raw_row, page_number, warnings)
                    if built is not None:
                        target.append(built)

        index: IndexSummarySheet | None = None
        index_pages = grouped.get(ExamSheetKind.INDEX_SUMMARY)
        if index_pages:
            index_raw = client.extract(
                instruction=(
                    f"{preamble}Transcribe the index page. Report every reference written "
                    "in the mortgage, lease/agreement, and easement/right-of-way columns as "
                    "one entry, including struck ones, and mark whether each is struck."
                ),
                images=_with_reading_views(index_pages),
                schema=ExtractedIndexSheet,
            )
            index, index_notes, struck = self._build_index(index_raw, index_pages[0].page_number)
            warnings.extend(index_notes)
            source_specific["index_struck_entries"] = struck
        else:
            warnings.append("No index page was found; cross-reference checks were skipped.")

        package = ExamPackage(
            file_number=request.file_number,
            source={"provider": "anthropic", "document_uri": request.document_uri},
            cover=cover,
            mortgages=mortgages,
            exceptions=exceptions,
            judgments=judgments,
            tax_parcels=tax_parcels,
            index=index,
        )
        return ExamExtractionResult(
            file_number=request.file_number,
            status=SourceResultStatus.SUCCEEDED,
            package=package,
            warnings=warnings,
            page_assignments=classification.assignments,
            source_specific=source_specific,
        )

    # -- canonical mapping --------------------------------------------------

    @staticmethod
    def _build_row(
        builder: Any, raw: ExtractedRow, page: int, warnings: list[str]
    ) -> Any | None:
        """Build one row, or report it. One unreadable row must not sink the file.

        A skipped mortgage, judgment, or exception leaves the declared count on the
        cover sheet unmatched, so reconciliation blocks on it; nothing is lost quietly.
        """

        try:
            return builder(raw, page)
        except ValidationError as exc:
            where = raw.src_page if raw.src_page and raw.src_page >= 1 else page
            fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
            warnings.append(
                f"A {builder.__name__.removeprefix('_build_')} row on p.{where} could not be "
                f"read ({fields}); it was left out and must be entered by hand."
            )
            return None

    @staticmethod
    def _provenance(sheet: ExamSheetKind, page: int, row: ExtractedRow) -> FieldProvenance:
        reported = row.src_page if row.src_page and row.src_page >= 1 else page
        return FieldProvenance(
            sheet=sheet,
            src_page=reported,
            src_text=row.src_text,
            confidence=normalize_confidence(row.confidence),
        )

    @classmethod
    def _build_cover(
        cls,
        raw: ExtractedCoverSheet,
        page: int,
        fallback_order_number: str,
    ) -> SearchCoverSheet:
        state = normalize_state(raw.state)
        address = None
        if raw.property_line1 or raw.property_city or raw.property_postal_code:
            address = Address(
                line1=raw.property_line1,
                city=raw.property_city,
                state=state,
                postal_code=raw.property_postal_code,
            )
        lsot = None
        if raw.lsot_book or raw.lsot_page:
            lsot = RecordingReference(book=raw.lsot_book, page=raw.lsot_page)

        return SearchCoverSheet(
            order_number=raw.order_number or fallback_order_number,
            county=raw.county,
            state=state,
            auditor_owners=raw.auditor_owners,
            buyers=raw.buyers,
            property_address=address,
            search_start_date=parse_sheet_date(raw.search_start_date),
            completed_date=parse_sheet_date(raw.completed_date),
            completed_by=raw.completed_by,
            last_shown_owner_transfer=lsot,
            declared_mortgage_count=raw.declared_mortgage_count,
            declared_judgment_count=raw.declared_judgment_count,
            declared_exception_count=raw.declared_exception_count,
            matters_of_concern=list(raw.matters_of_concern),
            provenance=cls._provenance(ExamSheetKind.SEARCH_COVER, page, raw),
        )

    @classmethod
    def _build_mortgage(cls, raw: ExtractedMortgageRow, page: int) -> MortgageEntry:
        return MortgageEntry(
            recording=RecordingReference(
                book=raw.book,
                page=raw.page,
                recorded_date=parse_sheet_date(raw.recorded_date),
            ),
            borrowers=raw.borrowers or "UNREADABLE",
            lender=raw.lender or "UNREADABLE",
            original_amount=parse_money(raw.amount),
            executed_date=parse_sheet_date(raw.executed_date),
            maturity_date=parse_sheet_date(raw.maturity_date, prefer_future=True),
            prior_owner=parse_bool(raw.prior_owner),
            heloc=parse_bool(raw.heloc),
            notes=raw.notes,
            provenance=cls._provenance(ExamSheetKind.MORTGAGES, page, raw),
        )

    @classmethod
    def _build_exception(cls, raw: ExtractedExceptionRow, page: int) -> ExceptionEntry:
        kinds: list[ExceptionInstrumentKind] = []
        for value in raw.instrument_kinds:
            try:
                kinds.append(ExceptionInstrumentKind(value.strip().lower()))
            except ValueError:
                continue
        named_plat = re.search(r"\b(plat|map|survey|vacation)\b", raw.instrument_name or "", re.I)
        if not kinds and named_plat:
            kinds = [ExceptionInstrumentKind.PLAT]
        if not kinds:
            kinds = [ExceptionInstrumentKind.EASEMENT]

        return ExceptionEntry(
            instrument_kinds=kinds,
            recording=RecordingReference(
                book=raw.book, page=raw.page, document_type=raw.record_series or None
            ),
            first_party=raw.first_party or "UNREADABLE",
            second_party=raw.second_party or "UNREADABLE",
            executed_date=parse_sheet_date(raw.executed_date),
            instrument_name=raw.instrument_name,
            notes=raw.notes,
            provenance=cls._provenance(ExamSheetKind.EXCEPTIONS, page, raw),
        )

    @classmethod
    def _build_judgment(cls, raw: ExtractedJudgmentRow, page: int) -> JudgmentEntry:
        recording = None
        if raw.book or raw.page:
            recording = RecordingReference(book=raw.book, page=raw.page)
        return JudgmentEntry(
            debtor=raw.debtor or "UNREADABLE",
            creditor=raw.creditor or "UNREADABLE",
            case_number=raw.case_number,
            court=raw.court,
            amount=parse_money(raw.amount),
            recording=recording,
            provenance=cls._provenance(ExamSheetKind.JUDGMENTS, page, raw),
        )

    @classmethod
    def _build_tax(cls, raw: ExtractedTaxRow, page: int) -> TaxParcelEntry:
        amount = parse_money(raw.special_assessment_amount)
        label = raw.special_assessment_label
        if amount is None and label and parse_money(label) is not None:
            # A form whose assessment boxes are printed amounts ("$16", "$18")
            # gets the ticked one reported as the label.
            amount, label = parse_money(label), None
        year = raw.tax_year
        if year is not None and 0 <= year < 100:
            year += 2000  # a sheet's "25" is tax year 2025
        return TaxParcelEntry(
            parcel_id=raw.parcel_id or "UNREADABLE",
            tax_year=year or date.today().year,
            taxpayer_name=raw.taxpayer_name,
            first_half_amount=parse_money(raw.first_half_amount),
            first_half_paid=parse_bool(raw.first_half_paid),
            second_half_amount=parse_money(raw.second_half_amount),
            second_half_paid=parse_bool(raw.second_half_paid),
            special_assessment_amount=amount,
            special_assessment_paid=parse_bool(raw.special_assessment_paid),
            special_assessment_label=label,
            cauv=parse_bool(raw.cauv),
            provenance=cls._provenance(ExamSheetKind.TAX, page, raw),
        )

    @classmethod
    def _build_index(
        cls, raw: ExtractedIndexSheet, page: int
    ) -> tuple[IndexSummarySheet, list[str], list[dict[str, Any]]]:
        """Index page, the warnings it raised, and the entries dropped as struck.

        A struck entry is dropped only when the extractor says what shows the strike.
        One marked struck without evidence stays live: keeping a satisfied matter costs
        a reviewer a moment, while dropping a live one can lose it from the commitment.
        """

        columns: dict[IndexColumn, list[RecordingReference]] = {c: [] for c in IndexColumn}
        warnings: list[str] = []
        struck: list[dict[str, Any]] = []
        for entry in raw.entries:
            ticked = bool(entry.annotation and _CHECK_MARK.search(entry.annotation))
            if entry.struck and entry.strike_evidence and ticked:
                # A tick means the abstractor carried the entry to a detail sheet. An
                # entry cannot be both carried and struck; treat it as live.
                warnings.append(
                    f"Index entry {entry.text!r} was reported struck but is ticked as carried "
                    "to a detail sheet; kept as live."
                )
            elif entry.struck and entry.strike_evidence:
                struck.append(
                    {
                        "column": entry.column.value,
                        "text": entry.text,
                        "evidence": entry.strike_evidence,
                        "annotation": entry.annotation,
                    }
                )
                continue
            elif entry.released and entry.column == IndexColumn.MORTGAGES:
                # Some abstractors note the release instead of striking the mortgage.
                struck.append(
                    {
                        "column": entry.column.value,
                        "text": entry.text,
                        "evidence": "release noted",
                        "annotation": entry.annotation,
                    }
                )
                continue
            elif entry.struck:
                warnings.append(
                    f"Index entry {entry.text!r} was reported struck with no evidence of a "
                    "strike; kept as live."
                )
            reference = parse_recording_ref(entry.text)
            if reference is None:
                warnings.append(
                    f"Index entry {entry.text!r} ({entry.column.value}) is not a book/page "
                    "reference; left out of the cross-check."
                )
                continue
            columns[entry.column].append(reference)

        index = IndexSummarySheet(
            mortgages=columns[IndexColumn.MORTGAGES],
            leases_agreements=columns[IndexColumn.LEASES_AGREEMENTS],
            easements_rights_of_way=columns[IndexColumn.EASEMENTS_RIGHTS_OF_WAY],
            name_searches=list(raw.name_searches),
            provenance=cls._provenance(ExamSheetKind.INDEX_SUMMARY, page, raw),
        )
        return index, warnings, struck


_CHECK_MARK = re.compile(r"✓|✔|\bcheck(?:ed|mark| mark)?\b|\btick(?:ed)?\b", re.IGNORECASE)

_RECORDING_REF = re.compile(
    r"\s*(?:(?P<series>[A-Za-z]{1,4})\.?\s+)?(?P<book>[0-9][0-9A-Za-z-]*)\s*/\s*(?P<page>[0-9A-Za-z-]+)\s*"
)
_RECORDING_REF_ANYWHERE = re.compile(
    r"(?<![\w/.])(?:(?P<series>[A-Za-z]{1,4})\.?\s+)?(?P<book>[0-9][0-9A-Za-z-]*)\s*/\s*(?P<page>[0-9][0-9A-Za-z-]*)"
)


def parse_recording_ref(raw: str | None) -> RecordingReference | None:
    """Find the ``book/page`` reference in an index-page entry.

    A leading record series (``DV 212/58``, ``OR 733/19``) is kept as the document
    type; it does not change the reference's identity. Labels and notes around the
    reference ("R/W: 1029/576 (P)", "1059/1265 R. 328/752") are ignored, and the
    first reference is taken; a release noted beside it is the entry's
    ``released`` flag, not part of its identity.
    """

    if raw is None:
        return None
    match = _RECORDING_REF.fullmatch(raw) or _RECORDING_REF_ANYWHERE.search(raw)
    if not match:
        return None
    series = match.group("series")
    return RecordingReference(
        book=match.group("book"),
        page=match.group("page"),
        document_type=series.upper() if series else None,
    )
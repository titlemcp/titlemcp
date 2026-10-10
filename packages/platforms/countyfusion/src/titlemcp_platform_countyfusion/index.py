"""A CountyFusion site as the index the release lookup asks."""

from __future__ import annotations

from datetime import date

from title_mcp.domain.recorder import (
    RecordedInstrument,
    index_search_name,
    normalize_instrument_number,
)
from titlemcp_platform_countyfusion.client import CountyFusionClient

#: Words that mark a business's name, which is indexed as written.
_BUSINESS_WORDS = frozenset(
    {
        "LLC",
        "INC",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "LP",
        "LLP",
        "TRUST",
        "BANK",
        "ASSOCIATION",
        "ASSN",
        "CHURCH",
        "HOMES",
        "PROPERTIES",
        "INVESTMENTS",
        "GROUP",
        "HOLDINGS",
    }
)


def surname_first(name: str) -> str:
    """A person's name the way the index writes it: "DOE JANE" for "JANE DOE"."""
    words = name.split()
    if len(words) < 2 or any(word in _BUSINESS_WORDS for word in words):
        return name
    return " ".join([words[-1], *words[:-1]])


class CountyFusionIndex:
    """The lookups ``title_mcp.sources.releases`` needs, in CountyFusion's terms.

    A document's links come from its detail, and each link already gives the
    linked document's number, type and recorded date. So following a mortgage
    to its release costs nothing more once the mortgage's detail is read.
    Everything seen is remembered for the life of the index, which is one
    release lookup.
    """

    def __init__(self, client: CountyFusionClient) -> None:
        self._client = client
        self._seen: dict[str, RecordedInstrument] = {}

    async def by_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        wanted = normalize_instrument_number(instrument_number)
        if wanted in self._seen:
            return [self._seen[wanted]]
        found = self._remember(await self._client.search_instrument(instrument_number))
        return [document for document in found if document.number == wanted]

    async def by_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        # The book-and-page search is the county's own form per county; not mapped yet.
        return []

    async def citing(self, instrument_number: str) -> list[RecordedInstrument]:
        # CountyFusion has no search of the text on document images.
        return []

    async def by_party(
        self, name: str, *, recorded_from: date | None = None
    ) -> list[RecordedInstrument]:
        # Names match from their start, and people are indexed surname first:
        # "JANE DOE" finds nothing where "DOE JANE" finds her.
        searched = index_search_name(name)
        for term in dict.fromkeys((surname_first(searched), searched)):
            found = await self._client.search_names(term, recorded_from=recorded_from)
            if found:
                return self._remember(found)
        return []

    async def with_links(self, document: RecordedInstrument) -> RecordedInstrument:
        inst_id = str(document.raw.get("inst_id") or "")
        if document.references or not document.raw.get("has_links") or not inst_id:
            return document
        detailed = await self._client.detail(inst_id)
        merged = document.model_copy(
            update={
                "references": detailed.references,
                "grantors": detailed.grantors or document.grantors,
                "grantees": detailed.grantees or document.grantees,
                "legal_description": detailed.legal_description or document.legal_description,
            }
        )
        self._seen[merged.number] = merged
        for entry in detailed.raw.get("linked") or []:
            stub = self._client.linked_stub(entry)
            self._seen.setdefault(stub.number, stub)
        return merged

    def _remember(self, documents: list[RecordedInstrument]) -> list[RecordedInstrument]:
        for document in documents:
            self._seen.setdefault(document.number, document)
        return documents

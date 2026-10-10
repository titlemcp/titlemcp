"""A PublicSearch site as the index the release lookup asks."""

from __future__ import annotations

from datetime import date

from title_mcp.domain.recorder import (
    RecordedInstrument,
    index_search_name,
    normalize_instrument_number,
)
from titlemcp_platform_publicsearch.client import PublicSearchClient, PublicSearchQuery

#: A name search for a common borrower returns hundreds of documents across a
#: lifetime of deeds and refinances; the most recent are the ones that matter.
PARTY_SEARCH_LIMIT = 300


class PublicSearchIndex:
    """The lookups ``title_mcp.sources.releases`` needs, in PublicSearch's terms.

    Every document a search returns is remembered for the life of the index,
    which is one release lookup. A borrower's name search usually returns the
    releases recorded to them, so following a mortgage's links rarely needs a
    search of its own.
    """

    def __init__(self, client: PublicSearchClient) -> None:
        self._client = client
        self._seen: dict[str, RecordedInstrument] = {}

    async def by_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        wanted = normalize_instrument_number(instrument_number)
        if wanted in self._seen:
            return [self._seen[wanted]]
        # A quick search on a number also matches documents that mention it, so
        # keep only the instrument itself.
        found = await self._search(PublicSearchQuery(search_value=instrument_number))
        return [document for document in found if document.number == wanted]

    async def by_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        # The quick search has no book-and-page form. Counties on PublicSearch
        # have numbered instruments for decades, so a mortgage still open is
        # almost always found by its number.
        return []

    async def citing(self, instrument_number: str) -> list[RecordedInstrument]:
        found = await self._search(
            PublicSearchQuery(search_value=instrument_number, search_ocr_text=True),
            excerpt_for=instrument_number,
        )
        return [
            document
            for document in found
            if document.cites(instrument_number) or document.text_excerpt
        ]

    async def by_party(
        self, name: str, *, recorded_from: date | None = None
    ) -> list[RecordedInstrument]:
        return await self._search(
            PublicSearchQuery(
                search_value=index_search_name(name),
                limit=PARTY_SEARCH_LIMIT,
                recorded_from=recorded_from,
            )
        )

    async def _search(
        self, query: PublicSearchQuery, *, excerpt_for: str | None = None
    ) -> list[RecordedInstrument]:
        found = await self._client.search(query, excerpt_for=excerpt_for)
        for document in found.documents:
            self._seen.setdefault(document.number, document)
        return found.documents

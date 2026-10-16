"""A Fidlar AVA site as the index the release lookup asks."""

from __future__ import annotations

from datetime import date

from title_mcp.domain.recorder import (
    InstrumentKind,
    InstrumentReference,
    RecordedInstrument,
    index_search_name,
    normalize_instrument_number,
)
from titlemcp_platform_fidlarava.client import FidlarAvaClient

#: Words that mark a business's name, which is searched whole.
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
        "MORTGAGE",
        "FINANCIAL",
        "CREDIT",
        "SAVINGS",
        "NATIONAL",
        "FEDERAL",
    }
)

#: Generational suffixes, which are not a surname.
_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV"})


def party_terms(name: str) -> list[tuple[str, str]]:
    """The (last or business name, first name) searches for a party, best first.

    A business is searched by its whole name. A person is searched by surname
    and first name: "JANE DOE" as ("DOE", "JANE"), and, in case the name was
    already given surname first, ("JANE", "DOE") after that.
    """
    words = name.split()
    if len(words) < 2 or any(word in _BUSINESS_WORDS for word in words):
        return [(name, "")] if name else []
    while len(words) > 2 and words[-1] in _SUFFIXES:
        words.pop()
    return list(dict.fromkeys([(words[-1], words[0]), (words[0], words[1])]))


class FidlarAvaIndex:
    """The lookups ``title_mcp.sources.releases`` needs, in Fidlar AVA's terms.

    Every search answers with each document's associated documents, by number
    only. ``with_links`` looks each one up to learn what it is, so following a
    mortgage to its release costs a search per linked document. Everything seen,
    and every number found missing, is remembered for the life of the index,
    which is one release lookup, so no number is searched twice.
    """

    def __init__(self, client: FidlarAvaClient) -> None:
        self._client = client
        self._seen: dict[str, RecordedInstrument] = {}
        self._missing: set[str] = set()

    async def by_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        wanted = normalize_instrument_number(instrument_number)
        if wanted in self._seen:
            return [self._seen[wanted]]
        if not wanted or wanted in self._missing:
            return []
        found = self._remember(await self._client.search_instrument(instrument_number.strip()))
        hits = [document for document in found if document.number == wanted]
        if not hits:
            self._missing.add(wanted)
        return hits

    async def by_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        # A search may match more than the one page, so only an exact match
        # counts. Leading zeros differ between a commitment and the index, so
        # they don't count; the search is tried as given, then without them.
        given = (book.strip(), page.strip())
        wanted = (given[0].lstrip("0"), given[1].lstrip("0"))
        hits: list[RecordedInstrument] = []
        for searched in dict.fromkeys((given, wanted)):
            found = self._remember(await self._client.search_book_page(*searched))
            hits = [
                document
                for document in found
                if (document.book.lstrip("0"), document.page.lstrip("0")) == wanted
            ]
            if hits:
                break
        return hits

    async def citing(self, instrument_number: str) -> list[RecordedInstrument]:
        # AVA has no search of the text on document images.
        return []

    async def by_party(
        self,
        name: str,
        *,
        recorded_from: date | None = None,
        recorded_to: date | None = None,
    ) -> list[RecordedInstrument]:
        for last, first in party_terms(index_search_name(name)):
            found = await self._client.search_party(
                last, first, recorded_from=recorded_from, recorded_to=recorded_to
            )
            if found:
                return self._remember(found)
        return []

    async def with_links(self, document: RecordedInstrument) -> RecordedInstrument:
        if all(reference.document_type for reference in document.references):
            return document
        references: list[InstrumentReference] = []
        for reference in document.references:
            if reference.document_type:
                references.append(reference)
                continue
            found = await self.by_instrument(reference.instrument_number)
            linked = found[0] if found else None
            references.append(
                InstrumentReference(
                    instrument_number=reference.instrument_number,
                    document_type=linked.document_type if linked else "",
                    kind=linked.kind if linked else InstrumentKind.OTHER,
                )
            )
        merged = document.model_copy(update={"references": references})
        self._seen[merged.number] = merged
        return merged

    def _remember(self, documents: list[RecordedInstrument]) -> list[RecordedInstrument]:
        for document in documents:
            self._seen.setdefault(document.number, document)
        return documents

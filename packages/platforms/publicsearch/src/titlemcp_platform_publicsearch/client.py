"""Kofile's PublicSearch, over the protocol its own sites speak.

Many county recorders run PublicSearch, each at ``<county>.<state>.publicsearch.us``.
The site talks to the browser over a websocket rather than a REST API, and
there is no documented interface, so this speaks the one the site does.

**Getting in.** A plain websocket connection is accepted and then closed. The
credential is a pair of httpOnly cookies, ``authToken`` and ``authToken.sig``,
issued by a GET of the landing page. The handshake must carry them, and the
same ``authToken`` value is repeated inside every message. One session serves
many searches, so it is kept for a few minutes rather than opened per search.

**Asking.** ``@kofile/FETCH_DOCUMENTS/v4`` carries a query; the answer arrives
as ``@kofile/FETCH_DOCUMENTS_FULFILLED/v6``. Other traffic shares the socket,
so replies are matched on ``correlationId`` rather than by arrival order.

**What comes back.** Each document carries ``marginalReferences``: the other
instruments the county's indexers linked it to, with their types. A mortgage
lists the releases and assignments recorded against it, and a release lists
the mortgage it discharges. That link is what makes a release lookup exact.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.domain.recorder import (
    InstrumentKind,
    InstrumentReference,
    RecordedInstrument,
    classify_instrument,
)

#: The site rejects a handshake that does not look like a browser.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)

#: Versioned by the platform. A bump here is a protocol change, not a typo.
FETCH_DOCUMENTS = "@kofile/FETCH_DOCUMENTS/v4"
FETCH_DOCUMENTS_FULFILLED = "FETCH_DOCUMENTS_FULFILLED"

#: Wide enough to reach the oldest instrument a county has imaged.
FULL_HISTORY = "16000101,29991231"

#: How long one landing-page session is reused before asking for another.
SESSION_SECONDS = 300

#: Payload fields left out of what a caller sees. The text read off the image
#: is the document's content, and the image links are signed and expire.
_DROPPED_FIELDS = frozenset({"ocrText", "highlights", "thumbnail", "images", "downloadLink"})


class PublicSearchQuery(BaseModel):
    """What to ask the index for.

    ``search_value`` is a party name, an instrument number, or a legal
    description. It is not an address: recorders do not index by street.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    search_value: str
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    recorded_from: date | None = None
    recorded_to: date | None = None
    department: str = "RP"
    #: Also search the text read off each document's image.
    search_ocr_text: bool = False

    @field_validator("search_value")
    @classmethod
    def _upper(cls, value: str) -> str:
        # The index is upper-cased; searching in mixed case silently narrows.
        return value.upper()

    @property
    def recorded_date_range(self) -> str:
        if self.recorded_from is None and self.recorded_to is None:
            return FULL_HISTORY
        start = (self.recorded_from or date(1600, 1, 1)).strftime("%Y%m%d")
        end = (self.recorded_to or date(2999, 12, 31)).strftime("%Y%m%d")
        return f"{start},{end}"

    def as_payload(self) -> dict[str, Any]:
        return {
            "query": {
                "limit": str(self.limit),
                "offset": str(self.offset),
                "department": self.department,
                "keywordSearch": False,
                "recordedDateRange": self.recorded_date_range,
                "searchOcrText": self.search_ocr_text,
                "searchType": "quickSearch",
                "searchValue": self.search_value,
            },
            "workspaceID": "search",
        }


class PublicSearchResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    documents: list[RecordedInstrument] = Field(default_factory=list)
    record_count: int = 0
    document_type_counts: dict[str, int] = Field(default_factory=dict)


class PublicSearchProtocolError(RuntimeError):
    """The county answered, and the answer was not a result set."""


class PublicSearchClient:
    """Speaks to one county's site. Holds no credential of its own.

    ``session_factory`` and ``connect_factory`` exist so tests can drive the
    whole mapping without a network, which the project requires.
    """

    def __init__(
        self,
        base_url: str,
        *,
        document_type_kinds: dict[str, InstrumentKind] | None = None,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.0,
        session_factory: Any = None,
        connect_factory: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.document_type_kinds = document_type_kinds or {}
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory or self._open_session
        self._connect_factory = connect_factory
        self._clock = clock
        self.min_interval_seconds = min_interval_seconds
        self._session: tuple[str, str] | None = None
        self._session_opened = 0.0
        self._last_search = float("-inf")

    @property
    def websocket_url(self) -> str:
        return self.base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"

    async def search(
        self, query: PublicSearchQuery, *, excerpt_for: str | None = None
    ) -> PublicSearchResult:
        """Run a search. ``excerpt_for`` keeps the image text around that phrase."""
        wait = self._last_search + self.min_interval_seconds - self._clock()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_search = self._clock()
        token, cookie = await self._current_session()
        message = {
            "type": FETCH_DOCUMENTS,
            "payload": query.as_payload(),
            "authToken": token,
            "correlationId": str(uuid.uuid4()),
            "sync": True,
        }
        payload = await self._ask(message, cookie)
        return self.to_result(payload, excerpt_for=excerpt_for)

    def to_result(
        self, payload: dict[str, Any], *, excerpt_for: str | None = None
    ) -> PublicSearchResult:
        meta = payload.get("meta") or {}
        by_hash = (payload.get("data") or {}).get("byHash") or {}
        statistics = (meta.get("statistics") or {}).get("docTypes") or []
        return PublicSearchResult(
            documents=[
                self.to_instrument(row, excerpt_for=excerpt_for) for row in by_hash.values()
            ],
            record_count=int(meta.get("numRecords") or 0),
            document_type_counts={
                _text(entry.get("label")): int(entry.get("hits") or 0) for entry in statistics
            },
        )

    def to_instrument(
        self, row: dict[str, Any], *, excerpt_for: str | None = None
    ) -> RecordedInstrument:
        code = _text(row.get("docTypeCode"))
        description = _text(row.get("docType"))
        book, page = _book_page(row)
        return RecordedInstrument(
            instrument_number=_text(row.get("instrumentNumber") or row.get("docNumber")),
            recorded_on=_parse_date(_text(row.get("recordedDate"))),
            document_type=description,
            document_type_code=code,
            kind=self._kind(code, description),
            grantors=_names(row.get("grantor")),
            grantees=_names(row.get("grantee")),
            book=book,
            page=page,
            legal_description=_legal(row),
            references=[
                InstrumentReference(
                    instrument_number=_text(reference.get("text")),
                    document_type=_text(reference.get("docTypeDesc")),
                    kind=self._kind(
                        _type_code(reference.get("docTypeDesc")), reference.get("docTypeDesc")
                    ),
                )
                for reference in row.get("marginalReferences") or []
                if _text(reference.get("text"))
            ],
            detail_url=f"{self.base_url}/doc/{row['id']}" if row.get("id") else None,
            text_excerpt=_excerpt(_text(row.get("ocrText")), excerpt_for),
            raw={key: value for key, value in row.items() if key not in _DROPPED_FIELDS},
        )

    # ------------------------------------------------------------- internals

    def _kind(self, code: str, description: Any) -> InstrumentKind:
        if code and code in self.document_type_kinds:
            return self.document_type_kinds[code]
        return classify_instrument(_text(description))

    async def _current_session(self) -> tuple[str, str]:
        now = self._clock()
        session = self._session
        if session is None or now - self._session_opened > SESSION_SECONDS:
            session = await self._session_factory()
            self._session, self._session_opened = session, now
        return session

    async def _open_session(self) -> tuple[str, str]:
        """One GET. The cookies it sets are the whole credential."""
        import http.cookiejar
        import urllib.request

        def fetch() -> tuple[str, str]:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            request = urllib.request.Request(
                self.base_url + "/", headers={"User-Agent": USER_AGENT}
            )
            with opener.open(request, timeout=self.timeout_seconds) as response:
                response.read(1)
            cookies = {cookie.name: cookie.value or "" for cookie in jar}
            token = cookies.get("authToken", "")
            return token, "; ".join(f"{name}={value}" for name, value in cookies.items())

        return await asyncio.to_thread(fetch)

    async def _ask(self, message: dict[str, Any], cookie: str) -> dict[str, Any]:
        connect = self._connect_factory
        if connect is None:
            from websockets.asyncio.client import connect as ws_connect

            connect = ws_connect

        wanted = message["correlationId"]
        async with connect(
            self.websocket_url,
            origin=self.base_url,
            additional_headers={"Cookie": cookie, "User-Agent": USER_AGENT},
        ) as socket:
            await socket.send(json.dumps(message))
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=self.timeout_seconds)
                reply = json.loads(raw)
                # The socket carries unrelated traffic. Match on the id we sent.
                if reply.get("correlationId") != wanted:
                    continue
                kind = str(reply.get("type", ""))
                if FETCH_DOCUMENTS_FULFILLED in kind:
                    return reply.get("payload") or {}
                if "REJECTED" in kind or "ERROR" in kind:
                    # A refused session is not reused.
                    self._session = None
                    raise PublicSearchProtocolError(f"{kind}: {str(reply.get('payload'))[:200]}")


def _text(value: Any) -> str:
    """Index values arrive with search highlighting markup in them."""
    if value is None:
        return ""
    return str(value).replace("<em>", "").replace("</em>", "").strip()


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [name for name in (_text(item) for item in value) if name]


def _legal(row: dict[str, Any]) -> str:
    described = _names(row.get("legalDescription"))
    if described:
        return " ".join(described)
    return " ".join(
        _text(legal.get("description"))
        for legal in row.get("legals") or []
        if isinstance(legal, dict) and _text(legal.get("description"))
    )


def _book_page(row: dict[str, Any]) -> tuple[str, str]:
    """Book and page, where the county still records them. ``--/--/--`` means none."""
    book = _text(row.get("book") or row.get("volume"))
    page = _text(row.get("page"))
    if not (book and page):
        parts = [part for part in _text(row.get("bookVolumePage")).split("/") if part.strip("-")]
        if len(parts) >= 2:
            book, page = parts[0], parts[-1]
    return book, page


def _excerpt(text: str, phrase: str | None, width: int = 80) -> str:
    """The image text around a phrase, enough to show why a document matched."""
    if not (text and phrase):
        return ""
    at = text.upper().find(phrase.upper())
    if at < 0:
        return ""
    return " ".join(text[max(0, at - width) : at + len(phrase) + width].split())


def _type_code(description: Any) -> str:
    """``RELS - RELEASE SATISFACTION`` carries its code; ``MORTGAGE RELEASE`` doesn't."""
    match = re.match(r"^\s*([A-Z0-9/]+)\s+-\s+", _text(description))
    return match.group(1) if match else ""


def _parse_date(value: str) -> date | None:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except (ValueError, AttributeError):
            continue
    return None

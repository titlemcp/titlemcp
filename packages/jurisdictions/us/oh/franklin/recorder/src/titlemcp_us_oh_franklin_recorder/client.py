"""The Franklin County, Ohio recorder, over the protocol its own site speaks.

The county's public search runs on Kofile's PublicSearch platform, which talks
to the browser over a websocket rather than a REST API. There is no documented
interface, so this speaks the one the site does.

**Getting in.** A plain websocket connection is accepted and then closed. The
credential is a pair of httpOnly cookies, ``authToken`` and ``authToken.sig``,
issued by a GET of the landing page. The handshake must carry them, and the
same ``authToken`` value is repeated inside every message. So a session is: one
HTTP GET, then a websocket that presents what it returned. No browser, no
credentials of ours, nothing to store.

**Asking.** ``@kofile/FETCH_DOCUMENTS/v4`` carries a query; the answer arrives
as ``@kofile/FETCH_DOCUMENTS_FULFILLED/v6``. Other traffic shares the socket,
so replies are matched on ``correlationId`` rather than by arrival order.

**A caution about what comes back.** The index is by party name and legal
description, not by street address. A name search returns that person's
documents across the whole county, which for a common name is a lot of other
people's property. Scoping to one parcel is ``chain.py``'s job, and it is the
part that decides whether an answer is right.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

BASE_URL = "https://franklin.oh.publicsearch.us"

#: The site rejects a handshake that does not look like a browser.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)

#: Versioned by the platform. A bump here is a protocol change, not a typo.
FETCH_DOCUMENTS = "@kofile/FETCH_DOCUMENTS/v4"
FETCH_DOCUMENTS_FULFILLED = "FETCH_DOCUMENTS_FULFILLED"

#: "RP" is real property. The site exposes other departments we have no use for.
DEPARTMENT_REAL_PROPERTY = "RP"

#: Wide enough to reach the oldest instrument the county has imaged.
FULL_HISTORY = "16000101,29991231"


class RecorderSearchQuery(BaseModel):
    """What to ask the index for.

    ``search_value`` is a party name or a legal description. It is not an
    address: the recorder does not index by street, which is the single most
    common wrong assumption about county records.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    search_value: str
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    recorded_date_range: str = FULL_HISTORY
    department: str = DEPARTMENT_REAL_PROPERTY
    search_ocr_text: bool = False

    @field_validator("search_value")
    @classmethod
    def _upper(cls, value: str) -> str:
        # The index is upper-cased; searching in mixed case silently narrows.
        return value.upper()

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


class RecorderDocument(BaseModel):
    """One recorded instrument, as the index describes it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_number: str = ""
    recorded_date: str = ""
    document_type: str = ""
    document_group: str = ""
    grantors: list[str] = Field(default_factory=list)
    grantees: list[str] = Field(default_factory=list)
    legal_description: str = ""
    book: str = ""
    volume: str = ""
    page: str = ""
    page_count: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RecorderDocument:
        return cls(
            instrument_number=_text(payload.get("instrumentNumber")),
            recorded_date=_text(payload.get("recordedDate")),
            document_type=_text(payload.get("docType")),
            document_group=_text(payload.get("docGroup")),
            grantors=_names(payload.get("grantor")),
            grantees=_names(payload.get("grantee")),
            legal_description=" ".join(_names(payload.get("legalDescription"))),
            book=_text(payload.get("book")),
            volume=_text(payload.get("volume")),
            page=_text(payload.get("page")),
            page_count=int(payload.get("pageCount") or 0),
            raw=payload,
        )


class RecorderSearchResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    documents: list[RecorderDocument] = Field(default_factory=list)
    record_count: int = 0
    document_type_counts: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class FranklinRecorderClient:
    """Speaks to the county. Holds no credential of its own.

    ``session_factory`` and ``connect_factory`` exist so tests can drive the
    whole mapping without a network, which the project requires.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        timeout_seconds: float = 30.0,
        session_factory: Any = None,
        connect_factory: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory or self._open_session
        self._connect_factory = connect_factory

    @property
    def websocket_url(self) -> str:
        return self.base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"

    async def search(self, query: RecorderSearchQuery) -> RecorderSearchResult:
        token, cookie = await self._session_factory()
        message = {
            "type": FETCH_DOCUMENTS,
            "payload": query.as_payload(),
            "authToken": token,
            "correlationId": str(uuid.uuid4()),
            "sync": True,
        }
        payload = await self._ask(message, cookie)
        return _to_result(payload)

    # ------------------------------------------------------------- internals

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
                    raise RecorderProtocolError(f"{kind}: {str(reply.get('payload'))[:200]}")


class RecorderProtocolError(RuntimeError):
    """The county answered, and the answer was not a result set."""


def _to_result(payload: dict[str, Any]) -> RecorderSearchResult:
    meta = payload.get("meta") or {}
    by_hash = (payload.get("data") or {}).get("byHash") or {}
    statistics = (meta.get("statistics") or {}).get("docTypes") or []
    return RecorderSearchResult(
        documents=[RecorderDocument.from_payload(row) for row in by_hash.values()],
        record_count=int(meta.get("numRecords") or 0),
        document_type_counts={
            _text(entry.get("label")): int(entry.get("hits") or 0) for entry in statistics
        },
        raw=payload,
    )


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

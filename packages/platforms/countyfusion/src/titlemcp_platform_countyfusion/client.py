"""Kofile's CountyFusion, as its public search pages speak it.

CountyFusion is a server-rendered site with no documented API. Everything here
is what its own pages send, with the public login a visitor gets from the
"Login as Public" button.

**A session.** A GET of the login page sets ``JSESSIONID`` and carries a form
token; posting the public login with that token and then accepting the
disclaimer opens the search pages. No account, nothing stored. Search state is
kept on the server against the session, so one session runs one search at a
time.

**A search** is three requests: the search is posted and answers with a
redirect, the redirect sets up the results and answers with another whose
query string carries the total, and the result list is a separate page.

**A document's links.** The result list only flags that a document has
marginal references. Its detail, a JSON call, lists them: for a release, the
mortgage it discharges; for a mortgage, each release and assignment recorded
against it, with the instrument number, type and recorded date of each.
"""

from __future__ import annotations

import asyncio
import html
import re
import threading
import time
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from title_mcp.domain.recorder import (
    InstrumentKind,
    InstrumentReference,
    RecordedInstrument,
    classify_instrument,
)
from titlemcp_platform_countyfusion.config import CountyFusionSiteConfig

USER_AGENT = (
    "Mozilla/5.0 (compatible; titlemcp-countyfusion/0.1; +https://github.com/titlemcp/titlemcp)"
)

#: Rows per result page; the largest the site offers.
PAGE_SIZE = 250

#: Result pages read for one name search. A borrower's lifetime of deeds and
#: mortgages fits on the first; a common name fills more with other people's.
MAX_PAGES = 4

_SEARCH_SESSION = "searchJobMain"

#: What the site says, instead of redirecting to results, when a search finds nothing.
_NOTHING_FOUND = "No documents were found"

#: An instrument search that finds nothing, run to open a session's detail calls.
_NO_SUCH_INSTRUMENT = {
    "SEARCHTYPE": "docNum",
    "INSTTYPEALL": "true",
    "INSTTYPE": "",
    "INSTNUM": "0",
    "INSTNUMEND": "",
}


class CountyFusionProtocolError(RuntimeError):
    """The site answered, and not the way its own pages expect."""


class CountyFusionClient:
    """One county's public session. Holds no credential of its own.

    ``session_factory`` exists so tests can drive the mapping without a
    network, which the project requires.
    """

    def __init__(
        self,
        config: CountyFusionSiteConfig,
        *,
        timeout_seconds: float = 60.0,
        session_factory: Any = None,
        clock: Any = time.monotonic,
        sleep: Any = time.sleep,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory or _requests_session
        self._clock = clock
        self._sleep = sleep
        self._http: Any = None
        self._searched = False
        self._last_request = float("-inf")
        # Search state lives on the server, per session: one search at a time.
        self._lock = threading.Lock()

    async def search_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        fields = {
            "SEARCHTYPE": "docNum",
            "INSTTYPEALL": "true",
            "INSTTYPE": "",
            "INSTNUM": instrument_number,
            "INSTNUMEND": "",
        }
        return await asyncio.to_thread(self._search, fields, 1)

    async def search_names(
        self, name: str, *, recorded_from: date | None = None, recorded_to: date | None = None
    ) -> list[RecordedInstrument]:
        fields = {
            "SEARCHTYPE": "allNames",
            "INSTTYPEALL": "true",
            "INSTTYPE": "",
            "PARTY": "both",
            "ALLNAMES": name.upper(),
            "SELECTEDNAMES": "",
            "FROMDATE": recorded_from.strftime("%m/%d/%Y") if recorded_from else "",
            "TODATE": recorded_to.strftime("%m/%d/%Y") if recorded_to else "",
            "DISTINCTRESULTS": "true",
        }
        return await asyncio.to_thread(self._search, fields, MAX_PAGES)

    async def detail(self, inst_id: str) -> RecordedInstrument:
        return await asyncio.to_thread(self._detail, inst_id)

    # ------------------------------------------------------------- mapping

    def rows(self, page: str) -> list[RecordedInstrument]:
        """The documents in a result list page."""
        ids = {
            int(match.group(1)): match.group(2)
            for match in re.finditer(r'documentRowInfo\[(\d+)\]\.instId\s*=\s*"(\d+)"', page)
        }
        table = _ResultTable()
        table.feed(page)
        found: list[RecordedInstrument] = []
        for index, cells in enumerate(table.rows):
            row = _label(table.headers, cells)
            names = _names(row.get("Name"))
            others = _names(row.get("Other Name"))
            # The column after each name says which side it is on: R grantor, E grantee.
            grantors, grantees = (others, names) if row.get("name_role") == "E" else (names, others)
            description = _text(row.get("Document Type"))
            found.append(
                RecordedInstrument(
                    instrument_number=_text(row.get("Instrument #")),
                    recorded_on=_parse_date(_text(row.get("Recorded"))),
                    document_type=description,
                    kind=self._kind(description),
                    grantors=grantors,
                    grantees=grantees,
                    book=_text(row.get("Book")),
                    page=_text(row.get("Page")),
                    legal_description=_text(row.get("Legal Description")),
                    raw={
                        "inst_id": ids.get(index, ""),
                        "has_links": bool(row.get("Marginal")),
                    },
                )
            )
        return found

    def document(self, payload: dict[str, Any], inst_id: str = "") -> RecordedInstrument:
        """A document's detail: its parties, legal, and the documents linked to it."""
        fields = [
            field for tab in payload.get("tabs") or [] for field in tab.get("dataFields") or []
        ]
        found: dict[str, Any] = {"names": {}, "legal": [], "references": []}
        for field in fields:
            kind, label = field.get("dataType"), field.get("label")
            if kind == "INSTNUM_ITERATE":
                found["number"] = _text(field.get("value"))
            elif kind == "INSTTYPE":
                found["type"] = _text(field.get("value"))
            elif kind == "BOOK_PAGE":
                found["book_page"] = _text(field.get("value"))
            elif kind == "DATE" and label == "Recorded Date":
                found["recorded"] = _text(field.get("value"))
            elif kind == "NAME":
                names = field.get("nameList") or {}
                found["names"].setdefault(names.get("label") or "", []).extend(
                    _text(entry.get("value")) for entry in names.get("value") or []
                )
            elif kind == "LOCATION":
                found["legal"].extend(
                    _text(entry.get("value"))
                    for entry in (field.get("legalList") or {}).get("value") or []
                )
            elif kind == "DOCLINK":
                for side in ("docFromList", "docToList"):
                    for entry in (field.get(side) or {}).get("value") or []:
                        found["references"].append(self._linked(entry))
        book, _, page = (part.strip() for part in found.get("book_page", "").partition("/"))
        description = found.get("type", "")
        linked = [entry for entry in found["references"] if entry["number"]]
        return RecordedInstrument(
            instrument_number=found.get("number", ""),
            recorded_on=_parse_date(found.get("recorded", "")),
            document_type=description,
            kind=self._kind(description),
            grantors=[name for name in found["names"].get("Grantor", []) if name],
            grantees=[name for name in found["names"].get("Grantee", []) if name],
            book=book,
            page=page,
            legal_description=" | ".join(entry for entry in found["legal"] if entry),
            references=[
                InstrumentReference(
                    instrument_number=entry["number"],
                    document_type=entry["type"],
                    kind=self._kind(entry["type"]),
                )
                for entry in linked
            ],
            raw={"inst_id": inst_id, "has_links": bool(linked), "linked": linked},
        )

    def linked_stub(self, entry: dict[str, Any]) -> RecordedInstrument:
        """What a link says about the document it points to, without fetching it."""
        return RecordedInstrument(
            instrument_number=entry["number"],
            recorded_on=_parse_date(entry["recorded"]),
            document_type=entry["type"],
            kind=self._kind(entry["type"]),
            book=entry["book"],
            page=entry["page"],
            raw={"inst_id": entry["inst_id"], "has_links": True},
        )

    # ------------------------------------------------------------- internals

    def _kind(self, description: str) -> InstrumentKind:
        normalized = " ".join(description.upper().split())
        if normalized in self.config.document_type_kinds:
            return self.config.document_type_kinds[normalized]
        return classify_instrument(normalized)

    def _linked(self, entry: dict[str, Any]) -> dict[str, Any]:
        value = entry.get("docValue") or {}
        volume_book_page = html.unescape(_text(entry.get("vbp"))).replace("\xa0", " ").split()
        return {
            "inst_id": str(value.get("instId") or ""),
            "number": _text(value.get("instNum") or entry.get("value")),
            "type": _text(value.get("desc") or _text(entry.get("description")).strip("()")),
            "recorded": _text(entry.get("date")),
            "book": volume_book_page[1].lstrip("0") if len(volume_book_page) >= 3 else "",
            "page": volume_book_page[2] if len(volume_book_page) >= 3 else "",
        }

    def _search(self, fields: dict[str, str], pages: int) -> list[RecordedInstrument]:
        with self._lock:
            return self._in_session(lambda: self._run_search(fields, pages))

    def _detail(self, inst_id: str) -> RecordedInstrument:
        with self._lock:
            return self._in_session(lambda: self._read_detail(inst_id), needs_search=True)

    def _in_session(self, work: Any, *, needs_search: bool = False) -> Any:
        """Run work in the public session, logging in again once if it has lapsed."""
        for attempt in range(2):
            if self._http is None or attempt:
                self._login()
            if needs_search and not self._searched:
                # The detail call answers only once the session has run a search.
                self._run_search(_NO_SUCH_INSTRUMENT, 1)
            try:
                return work()
            except CountyFusionProtocolError:
                if attempt:
                    raise
        raise CountyFusionProtocolError("unreachable")

    def _login(self) -> None:
        self._http = self._session_factory()
        self._searched = False
        county = self.config.county_key
        page = self._request("GET", f"/loginDisplay.action?countyname={county}")
        token = re.search(r'name="token" value="([^"]+)"', page.text)
        if token is None:
            raise CountyFusionProtocolError("The login page carried no form token.")
        login = self._request(
            "POST",
            "/login.action",
            data={
                "cmd": "login",
                "countyname": county,
                "scriptsupport": "yes",
                "apptype": "",
                "datasource": "",
                "userdatasource": "",
                "fraudsleuth": "false",
                "guest": "false",
                "public": "true",
                "startPage": "",
                "CountyFusionForceNewSession": "true",
                "struts.token.name": "token",
                "token": token.group(1),
                "username": "",
                "password": "",
            },
        )
        if "main.jsp" not in login.headers.get("Location", ""):
            raise CountyFusionProtocolError("The public login was refused.")
        self._request("POST", "/disclaimer.do", data={"cmd": "Accept"})

    def _run_search(self, fields: dict[str, str], pages: int) -> list[RecordedInstrument]:
        form = {
            "searchCategory": "ADVANCED",
            "searchSessionId": _SEARCH_SESSION,
            "PLATS": "",
            "QUARTER": "",
            "RECSPERPAGE": str(PAGE_SIZE),
            "userRefCode": "",
            "CASETYPE": "",
            "ORDERBY_LIST": "",
            "DATERANGE": "",
            **fields,
        }
        answer = self._request("POST", "/search/searchExecute.do?assessor=false", data=form)
        location = answer.headers.get("Location", "")
        if "searchResults.do" not in location:
            if _NOTHING_FOUND in answer.text:
                # A search that finds nothing answers with a page saying so.
                self._searched = True
                return []
            raise CountyFusionProtocolError("The search was not accepted; the session may be over.")
        self._searched = True
        # Resolved against the request's own address, whether the site sends it whole or not.
        answer = self._request(
            "GET", urljoin(self.config.base_url + "/search/searchExecute.do", location)
        )
        found: list[RecordedInstrument] = []
        for _ in range(pages):
            location = answer.headers.get("Location", "")
            if "SearchResultsView.jsp" not in location:
                # No results: the site answers with a page saying so.
                return found
            state = {key: values[0] for key, values in parse_qs(urlparse(location).query).items()}
            listing = self._request(
                "GET",
                f"/search/{self.config.county_key}/docs_SearchResultList.jsp",
                params={"scrollPos": "0", "searchSessionId": _SEARCH_SESSION},
            )
            found.extend(self.rows(listing.text))
            shown = re.search(r"Displaying (\d+)-(\d+) of (\d+)", state.get("navStateDisplay", ""))
            if not shown or int(shown.group(2)) >= int(shown.group(3)):
                return found
            answer = self._request(
                "GET",
                "/search/searchResults.do",
                params={
                    "searchSessionId": _SEARCH_SESSION,
                    "resultPageAction": "nav",
                    "sortColumn": state.get("curSortColumn", ""),
                    "sortDirection": state.get("curSortDirection", "asc"),
                    "navDirection": "next",
                    "startCursor": state.get("startCursor", "0"),
                },
            )
        return found

    def _read_detail(self, inst_id: str) -> RecordedInstrument:
        answer = self._request(
            "POST",
            "/search/getSearchResultsDetails.do",
            data={
                "instId": inst_id,
                "usage": "QV_ASSOC_DOCS",
                "displayMode": "QUICK_VIEW",
                "activeTab": "",
            },
        )
        try:
            payload = answer.json()
        except ValueError as exc:
            raise CountyFusionProtocolError("The document detail was not JSON.") from exc
        found = self.document(payload, inst_id)
        if not found.instrument_number:
            # A lapsed session answers with the tabs and no values in them.
            raise CountyFusionProtocolError("The document detail came back empty.")
        return found

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        wait = self._last_request + self.config.min_interval_seconds - self._clock()
        if wait > 0:
            self._sleep(wait)
        url = path if path.startswith("http") else self.config.base_url + path
        try:
            answer = self._http.request(
                method,
                url,
                timeout=self.timeout_seconds,
                allow_redirects=False,
                headers={"User-Agent": USER_AGENT},
                **kwargs,
            )
        finally:
            self._last_request = self._clock()
        answer.raise_for_status()
        return answer


def _requests_session() -> Any:
    import requests

    return requests.Session()


class _ResultTable(HTMLParser):
    """The result grid: header labels, and each row's cell text and span titles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headers: list[str] = []
        self.rows: list[list[dict[str, Any]]] = []
        self._in_header = self._in_cell = False
        self._text: list[str] = []
        self._titles: list[str] = []
        self._links = False
        self._row: list[dict[str, Any]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "th":
            self._in_header, self._text = True, []
        elif tag == "tr" and (attributes.get("id") or "").isdigit():
            self._row = []
        elif tag == "td" and self._row is not None:
            self._in_cell, self._text, self._titles, self._links = True, [], [], False
        elif tag == "span" and self._in_cell and attributes.get("title"):
            self._titles.append(attributes["title"] or "")
        elif (
            tag == "a"
            and self._in_cell
            and "showAssocDocsPopup" in (attributes.get("onclick") or "")
        ):
            self._links = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "th" and self._in_header:
            self.headers.append(" ".join("".join(self._text).split()))
            self._in_header = False
        elif tag == "td" and self._in_cell and self._row is not None:
            self._row.append(
                {
                    "text": " ".join("".join(self._text).split()),
                    "titles": list(self._titles),
                    "links": self._links,
                }
            )
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_header or self._in_cell:
            self._text.append(data)


def _label(headers: list[str], cells: list[dict[str, Any]]) -> dict[str, Any]:
    """A row by column label. Unlabelled columns after a name hold its side."""
    row: dict[str, Any] = {}
    for position, cell in enumerate(cells):
        label = headers[position] if position < len(headers) else ""
        before = headers[position - 1] if 0 < position <= len(headers) else ""
        if label == "Marginal":
            row[label] = cell["links"]
        elif label in ("Name", "Other Name"):
            row[label] = cell
        elif label:
            row[label] = cell["text"]
        elif before == "Document Type":
            row["name_role"] = cell["text"]
        elif before == "Name":
            row["other_name_role"] = cell["text"]
    return row


def _names(cell: dict[str, Any] | None) -> list[str]:
    """Every party in a name cell: the full list is in the span's title."""
    if not cell:
        return []
    for title in cell["titles"]:
        if title.strip():
            return [name.strip() for name in title.split("::") if name.strip()]
    return [cell["text"]] if cell["text"] else []


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_date(value: str) -> date | None:
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except (ValueError, AttributeError):
            continue
    return None

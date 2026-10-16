"""Fidlar's AVA, as its public search app speaks it.

AvaWeb is an Angular app over an ASP.NET web API. There is no documented API;
everything here is what the app itself sends, with the anonymous login it uses
for every visitor.

**The API's address.** The app reads ``appConfig.json`` from its own directory,
and its ``webApiBase`` is where the API lives.

**A session.** The app posts ``breeze/Settings`` for the county's search
options, then logs in with the password grant as ``anonymous``, password
``anonymous``, for a bearer token. No account, nothing stored. A token runs
out; the API says so with HTTP 401 or ``ResultAction`` 1, and the client logs
in again once.

**A search** is one post of a criteria object to ``breeze/Search``. The app
sends every criterion, empty unless searched, and the answer lists each
document found (``DocResults``) with its parties and its associated documents.

**The captcha.** The app sends a ``FidlarCaptchaSolution`` header with each
search, holding a reCAPTCHA token where the site wants one. Searches are
answered without one, so it is sent empty. A site that asks for one is
reported as having asked; no captcha is ever solved or worked around.

**A document's links.** ``AssociatedDocuments`` on a mortgage lists each
release and assignment recorded against it, and on a release, the mortgage it
discharges. Each entry gives only the other document's instrument number, so
what it is takes a search of that number.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from title_mcp.domain.recorder import (
    InstrumentKind,
    InstrumentReference,
    RecordedInstrument,
    classify_instrument,
)
from titlemcp_platform_fidlarava.config import FidlarAvaSiteConfig

USER_AGENT = (
    "Mozilla/5.0 (compatible; titlemcp-fidlarava/0.1; +https://github.com/titlemcp/titlemcp)"
)

#: Every criterion the app sends with a search, each empty unless searched.
CRITERIA_FIELDS = (
    "FirstName",
    "LastBusinessName",
    "StartDate",
    "EndDate",
    "DocumentName",
    "DocumentType",
    "SubdivisionName",
    "SubdivisionLot",
    "SubdivisionBlock",
    "MunicipalityName",
    "TractSection",
    "TractTownship",
    "TractRange",
    "TractQuarter",
    "TractQuarterQuarter",
    "AddressHouseNo",
    "AddressStreet",
    "AddressCity",
    "AddressZip",
    "ParcelNumber",
    "Book",
    "Page",
    "ReferenceNumber",
)

#: The anonymous login the app uses for every visitor.
ANONYMOUS_LOGIN = {"grant_type": "password", "username": "anonymous", "password": "anonymous"}

#: ``ResultAction`` for a token the API no longer accepts.
_UNAUTHORIZED = 1
#: ``ResultAction`` for a search the site wants paid for.
_INSUFFICIENT_FUNDS = 3

#: HTTP 412, Precondition Failed. The app answers it by asking the visitor to
#: wait and try again, and trying again is what fetches a new captcha token:
#: the request was turned away for its captcha.
_CAPTCHA_STATUS = 412

#: A refusal that only says nothing matched.
_NOTHING_FOUND = re.compile(r"\bno\b.*\b(found|match\w*|results?|records?|documents?)\b", re.I)


class FidlarAvaProtocolError(RuntimeError):
    """The site answered, and not the way its own app expects."""


class FidlarAvaCaptchaRequired(FidlarAvaProtocolError):
    """The site asked for a captcha before it would search.

    Nothing here solves or works around one. The county's index has to be
    searched by hand until the site answers without it.
    """


class FidlarAvaClient:
    """One county's anonymous session. Holds no credential of its own.

    ``session_factory`` exists so tests can drive the protocol without a
    network, which the project requires.
    """

    def __init__(
        self,
        config: FidlarAvaSiteConfig,
        *,
        timeout_seconds: float = 60.0,
        session_factory: Any = None,
        clock: Any = time.monotonic,
        sleep: Any = time.sleep,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.settings: dict[str, Any] = {}
        self._session_factory = session_factory or _requests_session
        self._clock = clock
        self._sleep = sleep
        self._http: Any = None
        self._api = ""
        self._token = ""
        self._last_request = float("-inf")
        # One login, and one request at a time so the spacing holds across threads.
        self._lock = threading.Lock()

    async def search_instrument(self, instrument_number: str) -> list[RecordedInstrument]:
        return await asyncio.to_thread(self._search, {"DocumentName": instrument_number})

    async def search_book_page(self, book: str, page: str) -> list[RecordedInstrument]:
        return await asyncio.to_thread(self._search, {"Book": book, "Page": page})

    async def search_party(
        self,
        last_or_business_name: str,
        first_name: str = "",
        *,
        recorded_from: date | None = None,
        recorded_to: date | None = None,
    ) -> list[RecordedInstrument]:
        fields = {
            "LastBusinessName": last_or_business_name.upper(),
            "FirstName": first_name.upper(),
            # The app sends dates as ISO dates, whatever it shows the visitor.
            "StartDate": recorded_from.isoformat() if recorded_from else "",
            "EndDate": recorded_to.isoformat() if recorded_to else "",
        }
        return await asyncio.to_thread(self._search, fields)

    # ------------------------------------------------------------- mapping

    def document(self, row: dict[str, Any]) -> RecordedInstrument:
        """One ``DocResults`` row: the document, its parties and its links."""
        description = _text(row.get("DocumentType"))
        sides: dict[str, list[str]] = {"1": [], "2": []}
        for party in row.get("Parties") or []:
            name = _joined(party.get("Name"), party.get("AdditionalName"))
            side = sides.get(str(party.get("PartyTypeId")))
            if name and side is not None:
                side.append(name)
        associated = [
            {
                "id": str(entry.get("Id") or ""),
                "number": _text(entry.get("Name")),
                "image_exists": bool(entry.get("ImageExists")),
            }
            for entry in row.get("AssociatedDocuments") or []
        ]
        legals = (
            _joined(legal.get("Description"), legal.get("Notes"))
            for legal in row.get("Legals") or []
        )
        return RecordedInstrument(
            instrument_number=_text(row.get("DocumentName")),
            recorded_on=_parse_date(_text(row.get("RecordedDateTime"))),
            document_type=description,
            kind=self._kind(description),
            # Party type 1 is the first party (on a mortgage, the mortgagor); 2 the second.
            grantors=sides["1"],
            grantees=sides["2"],
            book=_text(row.get("Book")),
            page=_text(row.get("Page")),
            legal_description=" | ".join(legal for legal in legals if legal),
            # The association names the other document by number only; its type
            # is learned by looking it up (FidlarAvaIndex.with_links).
            references=[
                InstrumentReference(instrument_number=entry["number"])
                for entry in associated
                if entry["number"]
            ],
            raw={
                "id": str(row.get("Id") or ""),
                "notes": _text(row.get("Notes")),
                "associated": associated,
            },
        )

    # ------------------------------------------------------------- internals

    def _kind(self, description: str) -> InstrumentKind:
        normalized = " ".join(description.upper().split())
        if normalized in self.config.document_type_kinds:
            return self.config.document_type_kinds[normalized]
        return classify_instrument(normalized)

    def _search(self, fields: dict[str, str]) -> list[RecordedInstrument]:
        criteria = dict.fromkeys(CRITERIA_FIELDS, "")
        criteria.update({name: value.strip() for name, value in fields.items()})
        with self._lock:
            if not self._token:
                # Not open yet, or opening it failed part way: start over.
                self._open()
            for attempt in range(2):
                if attempt:
                    # The token ran out: log in again, once.
                    self._login()
                answer = self._request(
                    "POST",
                    self._api + "breeze/Search",
                    json=criteria,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "FidlarCaptchaSolution": "",
                    },
                )
                body = _body(answer)
                if answer.status_code == 401 or body.get("ResultAction") == _UNAUTHORIZED:
                    continue
                return self._found(answer.status_code, body)
        raise FidlarAvaProtocolError("The site refused a fresh anonymous login's token.")

    def _found(self, status: int, body: dict[str, Any]) -> list[RecordedInstrument]:
        message = _text(body.get("Msg"))
        if status == _CAPTCHA_STATUS or "CAPTCHA" in message.upper():
            raise FidlarAvaCaptchaRequired(
                "The county's site asked for a captcha before it would search"
                + (f" ({message})" if message else f" (HTTP {status})")
                + ". Captchas are not solved or worked around here; search this county's "
                "index by hand."
            )
        if status == 402 or body.get("ResultAction") == _INSUFFICIENT_FUNDS:
            raise FidlarAvaProtocolError(
                "The county's site asks for payment before it will search."
            )
        if status >= 400:
            raise FidlarAvaProtocolError(
                f"The search was refused with HTTP {status}" + (f": {message}" if message else ".")
            )
        if body.get("Success") is False:
            if _NOTHING_FOUND.search(message):
                return []
            raise FidlarAvaProtocolError(
                message or f"The search failed (ResultAction {body.get('ResultAction')})."
            )
        return [self.document(row) for row in body.get("DocResults") or []]

    def _open(self) -> None:
        """The API's address and the county's settings, then the anonymous login."""
        self._http = self._session_factory()
        answer = self._request("GET", self.config.app_url + "appConfig.json")
        api = str(_body(answer, required=True).get("webApiBase") or "")
        if not api:
            raise FidlarAvaProtocolError("The app's configuration names no web API.")
        api = urljoin(self.config.app_url, api).rstrip("/") + "/"
        answer = self._request("POST", api + "breeze/Settings", json={})
        self.settings = _body(answer, required=True).get("Settings") or {}
        self._api = api
        self._login()

    def _login(self) -> None:
        answer = self._request("POST", self._api + "token", data=dict(ANONYMOUS_LOGIN))
        token = _body(answer).get("access_token") if answer.status_code < 400 else None
        if not token:
            raise FidlarAvaProtocolError("The anonymous login was refused.")
        self._token = str(token)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        wait = self._last_request + self.config.min_interval_seconds - self._clock()
        if wait > 0:
            self._sleep(wait)
        site = urlsplit(self.config.app_url)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": f"{site.scheme}://{site.netloc}",
            "Referer": self.config.app_url,
            **kwargs.pop("headers", {}),
        }
        try:
            return self._http.request(
                method, url, timeout=self.timeout_seconds, headers=headers, **kwargs
            )
        finally:
            self._last_request = self._clock()


def _requests_session() -> Any:
    import requests

    return requests.Session()


def _body(answer: Any, *, required: bool = False) -> dict[str, Any]:
    """An answer's JSON. The API answers refusals in JSON too, mostly."""
    if required and answer.status_code >= 400:
        raise FidlarAvaProtocolError(f"The site answered HTTP {answer.status_code}.")
    try:
        # Some of the app's files start with a byte order mark.
        payload = json.loads(answer.content.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        if answer.status_code >= 400:
            return {}
        raise FidlarAvaProtocolError("The site's answer was not JSON.") from exc
    if not isinstance(payload, dict):
        raise FidlarAvaProtocolError("The site's answer was not a JSON object.")
    return payload


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _joined(*parts: Any) -> str:
    return _text(" ".join(str(part) for part in parts if part))


def _parse_date(value: str) -> date | None:
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except (ValueError, AttributeError):
            continue
    return None

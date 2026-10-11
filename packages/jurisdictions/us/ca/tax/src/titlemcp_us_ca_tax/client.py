"""Reads a parcel from Contra Costa County's tax lookup, the JSON its own page calls."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

LOOKUP_PAGE_URL = "https://taxcolp.cccttc.us/lookup/"
APN_LOOKUP_URL = "https://taxcolp.cccttc.us/api/lookup/apn"
USER_AGENT = "titlemcp-us-ca-tax (+https://github.com/titlemcp/titlemcp)"
#: The lookup answers these when it has no such parcel: 400 for a number that
#: fails its check, 404 for one it doesn't have.
NOT_FOUND_STATUSES = frozenset({400, 404})


class TaxLookupError(RuntimeError):
    """The lookup answered with something other than a parcel or a not-found."""


class ContraCostaLookupClient:
    """Looks up one secured parcel by APN. Blocking; the connector runs it in a thread.

    ``fetch`` exists so tests can answer from fixtures without a network. It
    takes a URL and returns the HTTP status and the decoded JSON body.
    """

    def __init__(self, *, timeout_seconds: float = 30.0, fetch: Any = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._fetch = fetch or self._get_json

    def parcel(self, apn: str) -> dict[str, Any] | None:
        """The lookup's answer for this APN, or None when it has no such parcel."""
        status, payload = self._fetch(f"{APN_LOOKUP_URL}?{urllib.parse.urlencode({'apn': apn})}")
        if status in NOT_FOUND_STATUSES:
            return None
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("displayMessage") if isinstance(payload, dict) else None
            raise TaxLookupError(f"HTTP {status}" + (f": {message}" if message else ""))
        if payload.get("responseType") != "Lookup":
            raise TaxLookupError(f"unexpected answer type {payload.get('responseType')!r}")
        return payload

    def _get_json(self, url: str) -> tuple[int, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Referer": LOOKUP_PAGE_URL,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, None

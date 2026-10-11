"""Reads a parcel from the Shelby County Trustee's Tax Query, the JSON its own pages call."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TAX_QUERY_URL = "https://apps2.shelbycountytrustee.com/"
PARCEL_URL = "https://apps2.shelbycountytrustee.com/api/parcel"
USER_AGENT = "titlemcp-us-tn-tax (+https://github.com/titlemcp/titlemcp)"


class TrusteeError(RuntimeError):
    """The Tax Query answered with something other than a parcel or a not-found."""


def parcel_candidates(parcel_id: str) -> list[str]:
    """The parcel number as the parcel page takes it: block, one space, parcel.

    The Trustee pads it (``092007  00072``); any spacing or dashes are taken. A
    number written without them is split before its last five or six
    characters, the parcel within the block (``00072``, ``A00001``).
    """
    words = re.split(r"[\s-]+", parcel_id.strip().upper())
    words = [word for word in words if word]
    if len(words) > 1:
        return [" ".join(words)]
    compact = words[0] if words else ""
    return [f"{compact[:-n]} {compact[-n:]}" for n in (5, 6) if len(compact) > n]


class ShelbyTrusteeClient:
    """Reads one parcel's bills. Blocking; the connector runs it in a thread.

    ``fetch`` exists so tests can answer from fixtures without a network. It
    takes a URL and returns the HTTP status and the decoded JSON body, or None
    for a body that isn't JSON.
    """

    def __init__(self, *, timeout_seconds: float = 30.0, fetch: Any = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._fetch = fetch or self._get_json

    def parcel(self, parcel_id: str) -> dict[str, Any] | None:
        """The parcel's bills, or None when the Trustee has no such parcel."""
        found = [
            payload
            for payload in map(self._parcel, parcel_candidates(parcel_id))
            if payload is not None and _parcel_key(payload) == _key(parcel_id)
        ]
        # A number written without spaces could split two ways; both existing is ambiguous.
        return found[0] if len(found) == 1 else None

    def _parcel(self, parcel_id: str) -> dict[str, Any] | None:
        status, payload = self._fetch(
            f"{PARCEL_URL}?{urllib.parse.urlencode({'parcel': parcel_id})}"
        )
        if status == 404:
            return None
        if status != 200 or not isinstance(payload, dict):
            raise TrusteeError(f"parcel page answered HTTP {status}")
        if not payload.get("mergedBillData") and not payload.get("parcelBillData"):
            return None
        return payload

    def _get_json(self, url: str) -> tuple[int, Any]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds, context=_tls_context()
            ) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except ValueError:
                return exc.code, None


def _key(parcel_id: str) -> str:
    return re.sub(r"[\s-]+", "", parcel_id).upper()


def _parcel_key(payload: dict[str, Any]) -> str:
    bills = payload.get("mergedBillData") or payload.get("parcelBillData") or [{}]
    return _key(str(bills[0].get("parcel") or ""))


def _tls_context() -> ssl.SSLContext:
    # The Trustee's server needs legacy renegotiation, which OpenSSL 3 refuses
    # by default. Certificates and host names are still verified.
    context = ssl.create_default_context()
    context.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return context

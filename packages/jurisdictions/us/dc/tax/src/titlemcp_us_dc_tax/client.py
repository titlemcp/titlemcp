"""Queries the District's Integrated Tax System Public Extract, an ArcGIS feature layer.

The District republishes the extract under a new service name from time to
time, so the layer is found through its ArcGIS Online item, which keeps one id.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from typing import Any

#: The extract's ArcGIS Online item; its "url" is the current feature service.
ITEM_ID = "7d5e6cabd2304e779c719a4d5515af77"
ITEM_URL = f"https://www.arcgis.com/sharing/rest/content/items/{ITEM_ID}?f=json"
#: The service the item pointed at when this was written, if the item can't be read.
FALLBACK_SERVICE_URL = (
    "https://services.arcgis.com/neT9SoYxizqTHZPH/arcgis/rest/services/ITSPE_08172026/FeatureServer"
)
USER_AGENT = "titlemcp-us-dc-tax (+https://github.com/titlemcp/titlemcp)"
#: How long the layer's address and last-edit date are trusted before reading them again.
METADATA_SECONDS = 3600


class ArcGISError(RuntimeError):
    """The layer answered with an error instead of features."""


class ExtractClient:
    """Reads parcels from the extract. Blocking; the connector runs it in a thread.

    ``fetch`` exists so tests can answer from fixtures without a network.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        fetch: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._fetch = fetch or self._get_json
        self._clock = clock
        self._layer_url: str | None = None
        self._edited: date | None = None
        self._metadata_read_at = float("-inf")

    def parcels(self, ssl_values: list[str]) -> list[dict[str, Any]]:
        """Rows whose SSL is one of these."""
        quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in ssl_values)
        params = {
            "where": f"SSL IN ({quoted})",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }
        payload = self._fetch(f"{self.layer_url()}/query?{urllib.parse.urlencode(params)}")
        if "error" in payload:
            raise ArcGISError(str(payload["error"].get("message") or payload["error"]))
        return [feature.get("attributes") or {} for feature in payload.get("features") or []]

    def last_edited(self) -> date | None:
        """When the District last refreshed the layer."""
        self._read_metadata()
        return self._edited

    def layer_url(self) -> str:
        self._read_metadata()
        return self._layer_url or f"{FALLBACK_SERVICE_URL}/0"

    def _read_metadata(self) -> None:
        if self._clock() - self._metadata_read_at < METADATA_SECONDS and self._layer_url:
            return
        try:
            service = self._fetch(ITEM_URL).get("url") or FALLBACK_SERVICE_URL
        except (OSError, ValueError):
            service = FALLBACK_SERVICE_URL
        layer_url = f"{service.rstrip('/')}/0"
        layer = self._fetch(f"{layer_url}?f=json")
        edited = (layer.get("editingInfo") or {}).get("dataLastEditDate")
        self._layer_url = layer_url
        self._edited = (
            datetime.fromtimestamp(edited / 1000, tz=UTC).date()
            if isinstance(edited, int | float)
            else None
        )
        self._metadata_read_at = self._clock()

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

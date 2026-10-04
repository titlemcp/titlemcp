"""Fetching, caching and parsing OFAC's list files, and what changed between versions."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from title_mcp.sources.ofac.models import (
    AliasQuality,
    EntryType,
    ListName,
    ListVersion,
    SanctionsEntry,
    SanctionsList,
)

BASE_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports"
FILES = {SanctionsList.SDN: "SDN.XML", SanctionsList.CONSOLIDATED: "CONSOLIDATED.XML"}
_TYPES = {
    "individual": EntryType.INDIVIDUAL,
    "entity": EntryType.ENTITY,
    "vessel": EntryType.VESSEL,
    "aircraft": EntryType.AIRCRAFT,
}


class ListFetcher(Protocol):
    def fetch(self, url: str, timeout: float) -> bytes: ...


class HttpFetcher:
    def fetch(self, url: str, timeout: float) -> bytes:
        import requests

        response = requests.get(url, timeout=timeout, headers={"User-Agent": "titlemcp"})
        response.raise_for_status()
        return response.content


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _children(element: ET.Element, name: str) -> Iterable[ET.Element]:
    for child in element:
        if _local(child.tag) == name:
            yield from child


def _full(first: str, last: str) -> str:
    return " ".join(p for p in (first, last) if p).strip()


def parse(data: bytes, sanctions_list: SanctionsList) -> tuple[list[SanctionsEntry], str, int]:
    """Entries, publish date and record count from an OFAC XML list (SDN.XML format)."""

    root = ET.fromstring(data)
    publish_date, count = "", 0
    entries: list[SanctionsEntry] = []
    for node in root:
        tag = _local(node.tag)
        if tag == "publshInformation":
            publish_date = _text(node, "Publish_Date")
            count = int(_text(node, "Record_Count") or 0)
            continue
        if tag != "sdnEntry":
            continue
        names = [ListName(full_name=_full(_text(node, "firstName"), _text(node, "lastName")))]
        for aka in _children(node, "akaList"):
            full = _full(_text(aka, "firstName"), _text(aka, "lastName"))
            if full:
                weak = _text(aka, "category").lower() == "weak"
                names.append(
                    ListName(
                        full_name=full,
                        quality=AliasQuality.WEAK if weak else AliasQuality.STRONG,
                        alias_type=_text(aka, "type"),
                    )
                )
        entries.append(
            SanctionsEntry(
                uid=_text(node, "uid"),
                sanctions_list=sanctions_list,
                entry_type=_TYPES.get(_text(node, "sdnType").lower(), EntryType.ENTITY),
                names=names,
                programs=[p.text.strip() for p in _children(node, "programList") if p.text],
                dates_of_birth=[
                    _text(d, "dateOfBirth") for d in _children(node, "dateOfBirthList")
                ],
                places_of_birth=[
                    _text(d, "placeOfBirth") for d in _children(node, "placeOfBirthList")
                ],
                nationalities=[_text(d, "country") for d in _children(node, "nationalityList")],
                address_countries=sorted(
                    {_text(a, "country") for a in _children(node, "addressList")} - {""}
                ),
                remarks=_text(node, "remarks"),
            )
        )
    return entries, publish_date, count or len(entries)


class ListStore:
    """The lists on disk, refreshed when older than ``max_age_hours``."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        fetcher: ListFetcher | None = None,
        max_age_hours: float = 24.0,
        timeout: float = 120.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.fetcher = fetcher or HttpFetcher()
        self.max_age_hours = max_age_hours
        self.timeout = timeout

    def _path(self, sanctions_list: SanctionsList) -> Path:
        return self.cache_dir / FILES[sanctions_list]

    def load(
        self, sanctions_list: SanctionsList, *, refresh: bool = False
    ) -> tuple[list[SanctionsEntry], ListVersion]:
        path = self._path(sanctions_list)
        url = f"{BASE_URL}/{FILES[sanctions_list]}"
        stale = (
            not path.exists()
            or (datetime.now(UTC).timestamp() - path.stat().st_mtime) / 3600 > self.max_age_hours
        )
        if refresh or stale:
            try:
                data = self.fetcher.fetch(url, self.timeout)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                previous = path.read_bytes() if path.exists() else None
                if previous is not None and previous != data:
                    path.with_suffix(".previous.xml").write_bytes(previous)
                path.write_bytes(data)
            except Exception:  # noqa: BLE001  (a stale copy beats none; the caller sees its date)
                if not path.exists():
                    raise
        data = path.read_bytes()
        entries, publish_date, count = parse(data, sanctions_list)
        version = ListVersion(
            sanctions_list=sanctions_list,
            publish_date=publish_date,
            record_count=count,
            sha256=hashlib.sha256(data).hexdigest(),
            source_url=url,
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )
        return entries, version

    def previous(self, sanctions_list: SanctionsList) -> list[SanctionsEntry]:
        """The version before the current one, if the cache kept it."""

        path = self._path(sanctions_list).with_suffix(".previous.xml")
        return parse(path.read_bytes(), sanctions_list)[0] if path.exists() else []


def changed(old: list[SanctionsEntry], new: list[SanctionsEntry]) -> list[SanctionsEntry]:
    """Entries added or changed in ``new``: what parties need re-screening against."""

    before = {e.uid: e.model_dump_json() for e in old}
    return [e for e in new if before.get(e.uid) != e.model_dump_json()]

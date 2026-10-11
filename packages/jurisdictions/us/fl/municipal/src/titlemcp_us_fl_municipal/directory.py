"""Florida's local governments, read from the packaged directory.

One entry for each of Florida's 67 counties and each city of 20,000 people or
more. Names are matched the way people write them: "Fort Lauderdale", "Ft.
Lauderdale" and "City of Fort Lauderdale" are one city, and "Dade" is
Miami-Dade.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from title_mcp.domain.municipal import GovernmentKind, MunicipalOffice

DATA = Path(__file__).with_name("data") / "directory.json"
COVERAGE = "Florida's 67 counties and its cities of 20,000 people or more"

_ABBREVIATIONS = {"st": "saint", "ft": "fort", "mt": "mount"}
_PLACE_TYPES = ("city", "town", "village")
_COUNTY_ALIASES = {"dade": "miamidade"}
_UNINCORPORATED = {"unincorporated", "unincorporatedarea", "none"}


class FloridaDirectory:
    """The packaged entries, found by county or city name."""

    def __init__(self, offices: list[MunicipalOffice]) -> None:
        self.offices = offices
        self._counties = {
            _county_key(office.name): office
            for office in offices
            if office.kind is GovernmentKind.COUNTY
        }
        self._cities: dict[str, list[MunicipalOffice]] = {}
        for office in offices:
            if office.kind is GovernmentKind.MUNICIPALITY:
                self._cities.setdefault(name_keys(office.name)[0], []).append(office)

    def county(self, name: str | None) -> MunicipalOffice | None:
        if not name:
            return None
        key = _county_key(name)
        return self._counties.get(_COUNTY_ALIASES.get(key, key))

    def municipality(self, name: str, county: str | None = None) -> MunicipalOffice | None:
        """The city by name; where two share a name, the one in the county given."""
        for key in name_keys(name):
            matches = self._cities.get(key, [])
            if len(matches) > 1 and county:
                matches = [
                    office
                    for office in matches
                    if _county_key(office.county) == _county_key(county)
                ]
            if len(matches) == 1:
                return matches[0]
        return None


def is_unincorporated(name: str | None) -> bool:
    return bool(name) and "".join(_words(name or "")) in _UNINCORPORATED


def name_keys(name: str) -> list[str]:
    """The name as given, then without a trailing "city", "town" or "village"."""
    words = _words(name)
    keys = ["".join(words)]
    if len(words) > 1 and words[-1] in _PLACE_TYPES:
        keys.append("".join(words[:-1]))
    return keys


def _county_key(name: str) -> str:
    words = _words(name)
    if len(words) > 1 and words[-1] == "county":
        words = words[:-1]
    return "".join(words)


def _words(name: str) -> list[str]:
    words = re.sub(r"[^a-z0-9]+", " ", name.lower().replace("'", "")).split()
    if len(words) > 2 and words[0] in _PLACE_TYPES and words[1] == "of":
        words = words[2:]
    return [_ABBREVIATIONS.get(word, word) for word in words]


@cache
def load_directory() -> FloridaDirectory:
    entries = json.loads(DATA.read_text("utf-8"))
    return FloridaDirectory([MunicipalOffice.model_validate(entry) for entry in entries])

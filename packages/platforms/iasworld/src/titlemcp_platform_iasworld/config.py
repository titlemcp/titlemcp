from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction


class AuditorSearchMode(StrEnum):
    ADDRESS = "address"
    OWNER = "owner"
    PARCEL_ID = "parid"


class DetailProfile(StrEnum):
    """Which iasWorld datalet detail layout a county uses.

    All are iasWorld, but the datalet templates differ in section names and
    field labels:

    - ``CLASSIC`` (Franklin): a combined ``Owner`` section plus ``Most Recent
      Transfer`` / ``<year> Tax Status`` / ``<year> Auditor`` / ``Annual Taxes``.
    - ``PUBLIC_ACCESS`` (Clermont): split ``Parcel`` / ``Owner`` / ``Tax Mailing
      Name and Address`` / ``Legal`` / ``Taxes Charged`` sections with numbered
      labels (``Owner 1``, ``Address 1``, ``Legal Desc 1``).
    - ``PUBLIC_ACCESS_DETAILED`` (Butler): the same numbered labels, but owner
      and legal share one ``Owner and Legal`` table, mailing is ``Taxbill
      Mailing Address``, and the page also serves ``Current Value``,
      ``Transfers`` and half-year ``Current Year Real Estate Taxes`` tables.
      Both Public Access variants are table-driven: see
      ``PUBLIC_ACCESS_LAYOUTS`` in ``client.py``, where a county that renames
      sections is a data entry rather than a new profile.
    - ``PUBLIC_ACCESS_KEYED`` (Montgomery): the same split sections, labelled
      rather than numbered (``Name``, ``Mailing Address``, ``Legal
      Description``). The owner table is a single column under a ``Name``
      header, multi-line values continue on rows whose label cell is blank, and
      ``Sales`` is oldest first.
    - ``SUMMARY_SECTIONS`` (Lucas): a ``Summary - `` tabbed datalet. This tab
      carries no owner, mailing address or legal description at all, so those
      come from the search hit, and its value table is transposed with the
      valuation basis in the columns.
    - ``LAKE`` (Lake): singular labels (``Owner Name``, ``Legal Description``)
      under ``Owner Name and Mailing Address`` / ``Legal Description
      Information``, prefixed value tables (``Appraised (Market - 100%) Value``,
      ``Assessed Value (35%)``) and ``Taxes Due``. Lake serves no
      ``DataletHeader`` table and writes ``-`` for empty fields.
    """

    CLASSIC = "classic"
    PUBLIC_ACCESS = "public_access"
    PUBLIC_ACCESS_DETAILED = "public_access_detailed"
    PUBLIC_ACCESS_KEYED = "public_access_keyed"
    SUMMARY_SECTIONS = "summary_sections"
    LAKE = "lake"


def _normalize_mode(value: str | AuditorSearchMode) -> AuditorSearchMode:
    if isinstance(value, AuditorSearchMode):
        return value
    normalized = str(value).lower().strip()
    aliases = {
        "parcel": AuditorSearchMode.PARCEL_ID,
        "parcel_id": AuditorSearchMode.PARCEL_ID,
        "parid": AuditorSearchMode.PARCEL_ID,
        "owner": AuditorSearchMode.OWNER,
        "address": AuditorSearchMode.ADDRESS,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("mode must be one of address, owner, or parid") from exc


def resolve_auditor_search_mode(
    mode: str | AuditorSearchMode | None = None,
    *,
    parcel_id: str | None = None,
    owner_name: str | None = None,
    address: str | None = None,
    address_number: str | int | None = None,
    street_name: str | None = None,
) -> AuditorSearchMode:
    if mode:
        try:
            return _normalize_mode(mode)
        except ValueError:
            pass
    if parcel_id:
        return AuditorSearchMode.PARCEL_ID
    if owner_name:
        return AuditorSearchMode.OWNER
    if address or address_number or street_name:
        return AuditorSearchMode.ADDRESS
    return AuditorSearchMode.ADDRESS


class IasWorldSiteConfig(BaseModel):
    """Per-county configuration for a Tyler iasWorld auditor/property site.

    The iasWorld scraping behavior (search forms, datalet parsing, canonical
    mapping) is identical across counties. Only these knobs differ:

    - ``base_url``: the parent of ``search/commonsearch.aspx`` and
      ``Datalets/Datalet.aspx`` (e.g. ``https://property.<county>.com/_web/`` or a
      bare domain like ``https://www.mcrealestate.org/``).
    - ``district_code``: the iasWorld ``jur`` parameter (Franklin ``025``,
      Montgomery/Stark ``000``).
    - ``mode_map``: overrides the ``mode=`` URL value per search mode (Summit and
      Lake serve a unified ``realprop`` search instead of ``address``).
    - ``form_field_overrides``: renames the POST field names the client submits.
      Most counties share the classic iasWorld names (``inpNumber``, ``inpOwner``,
      ``inpAdrdir``, ``inpUnit``); Lake's unified ``realprop`` form instead uses
      ``inpNo`` for the address number and ``inpOwner1`` for the owner. Keys are
      the logical (classic) field names; values are the names this site expects.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    source_id: str
    county: str
    state: str
    country: str = "US"
    name: str
    base_url: str
    district_code: str = "000"
    owner: str | None = None
    priority: int = Field(default=230, ge=0)
    mode_map: dict[AuditorSearchMode, str] = Field(default_factory=dict)
    # Renames the POST field names submitted to the search form. Empty (the
    # default) means the classic iasWorld names; Lake's realprop form needs
    # {"inpNumber": "inpNo", "inpOwner": "inpOwner1"} (see docstring).
    form_field_overrides: dict[str, str] = Field(default_factory=dict)
    # Most Ohio iasWorld counties use purely numeric parcel IDs (Franklin
    # "01000012300"); set False for counties with alphanumeric parcels such as
    # Clermont ("100200C003D", "100200.034C") so letters/dots are preserved.
    numeric_parcel_ids: bool = True
    # Which datalet detail layout the county serves (see DetailProfile).
    detail_profile: DetailProfile = DetailProfile.CLASSIC
    # Some counties' parcel IDs contain significant internal spaces (Montgomery
    # "A01 00000 0001") that the search form expects verbatim; the default strips
    # whitespace when compacting. Set True to preserve spaces in alphanumeric
    # parcels. Only meaningful when numeric_parcel_ids=False.
    preserve_parcel_whitespace: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country", "state", mode="before")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value).strip().upper()

    @field_validator("base_url", mode="before")
    @classmethod
    def _ensure_trailing_slash(cls, value: str) -> str:
        text = str(value).strip()
        return text if text.endswith("/") else f"{text}/"

    def url_mode(self, mode: AuditorSearchMode) -> str:
        return self.mode_map.get(mode, mode.value)

    def search_url(self, mode: AuditorSearchMode | str) -> str:
        mode_value = self.url_mode(_normalize_mode(mode))
        return f"{self.base_url}search/commonsearch.aspx?mode={mode_value}"

    @property
    def official_search_pages(self) -> dict[str, str]:
        return {mode.value: self.search_url(mode) for mode in AuditorSearchMode}

    @property
    def slug(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", self.county.lower()).strip("_")
        return slug or "county"

    @property
    def tool_name(self) -> str:
        return f"{self.slug}_auditor_search"

    @property
    def tool_title(self) -> str:
        return f"{self.county} Auditor Search"

    @property
    def jurisdiction(self) -> Jurisdiction:
        return Jurisdiction(country=self.country, state=self.state, county=self.county)

    @property
    def jurisdiction_scope(self) -> JurisdictionScope:
        return JurisdictionScope(country=self.country, state=self.state, county=self.county)

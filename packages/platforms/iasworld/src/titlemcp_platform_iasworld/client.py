from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from titlemcp_platform_iasworld.config import (
    AuditorSearchMode,
    DetailProfile,
    IasWorldSiteConfig,
)
from titlemcp_platform_iasworld.models import (
    IasWorldAuditorParcelDetail,
    IasWorldAuditorSearchHit,
    IasWorldAuditorSearchQuery,
    IasWorldAuditorSearchResponse,
)


class IasWorldAuditorClientError(RuntimeError):
    pass


@dataclass
class _TableCapture:
    attrs: dict[str, str]
    rows: list[list[str]] = field(default_factory=list)
    current_row: list[str] | None = None
    current_cell: list[str] | None = None


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}
        self.selects: dict[str, str] = {}
        self._select_name: str | None = None
        self._select_has_selected = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = _attrs(attrs)
        if tag == "input":
            name = attributes.get("name")
            if name:
                self.inputs[name] = attributes.get("value", "")
        elif tag == "select":
            self._select_name = attributes.get("name")
            self._select_has_selected = False
            if self._select_name:
                self.selects.setdefault(self._select_name, "")
        elif tag == "option" and self._select_name:
            value = attributes.get("value", "")
            if attributes.get("selected") is not None:
                self.selects[self._select_name] = value
                self._select_has_selected = True
            elif not self._select_has_selected and self.selects.get(self._select_name, "") == "":
                self.selects[self._select_name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select_name = None
            self._select_has_selected = False

    @property
    def form_data(self) -> dict[str, str]:
        data = dict(self.inputs)
        data.update(self.selects)
        return data


def _classify_header(label: str) -> str | None:
    """Map a results-table header label to a canonical field, or None to ignore.

    iasWorld builds vary the labels ("Parcel ID" / "Parcel #" / "Parcel"; "Parcel
    Location" / "Parcel Address" / "Address"; "Owner"), and interleave columns the
    canonical record does not use (LUC, Route, TaxYr, Land Use, the select-all
    checkbox). Address-ish labels are checked before "parcel" so "Parcel Location"
    and "Parcel Address" map to address, not parcel.
    """
    text = re.sub(r"[^a-z0-9 ]", " ", label.lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if "location" in text or "address" in text or "situs" in text:
        return "address"
    if "owner" in text:
        return "owner"
    if "parcel" in text or text == "pin":
        return "parcel"
    if "legal" in text:
        return "legal"
    return None


class _SearchResultsParser(HTMLParser):
    """Parse the iasWorld results table.

    Columns are mapped by their ``<th>`` header labels (``_classify_header``) so
    any build's column order — including owner/address swaps and interleaved
    extra columns — is handled automatically. Tables without headers fall back to
    the classic positional order (parcel, address, owner, legal).
    """

    def __init__(
        self,
        *,
        numeric_parcel_ids: bool = True,
        preserve_parcel_whitespace: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._numeric_parcel_ids = numeric_parcel_ids
        self._preserve_parcel_whitespace = preserve_parcel_whitespace
        self.rows: list[IasWorldAuditorSearchHit] = []
        # Field name (or None) per header column index, from the latest header row.
        self._headers: list[str | None] = []
        self._in_row = False
        self._row_is_data = False
        self._row_has_header = False
        self._pending_headers: list[str | None] = []
        self._in_cell = False
        self._cell_is_header = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._parcel_token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = _attrs(attrs)
        if tag == "tr":
            self._in_row = True
            self._row_is_data = "SearchResults" in attributes.get("class", "")
            self._row_has_header = False
            self._pending_headers = []
            self._cells = []
            self._parcel_token = None
            self._in_cell = False
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_is_header = tag == "th"
            self._cell_parts = []
            if tag == "th":
                self._row_has_header = True
        elif self._in_row and self._row_is_data and tag == "input":
            value = attributes.get("value", "")
            if _looks_like_parcel_token(value):
                self._parcel_token = value

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = _clean_text(" ".join(self._cell_parts))
            if self._cell_is_header:
                self._pending_headers.append(_classify_header(text))
            else:
                self._cells.append(text)
            self._in_cell = False
            self._cell_parts = []
        elif tag == "tr" and self._in_row:
            if self._row_has_header:
                # Only adopt a genuine column header (one naming a parcel column);
                # ignore stray single-cell header rows like "Selection Manager".
                if any(field == "parcel" for field in self._pending_headers):
                    self._headers = self._pending_headers
            elif self._row_is_data:
                self._finish_row()
            self._in_row = False

    def _map_columns(self, cells: list[str]) -> dict[str, str] | None:
        # Header-driven: align labelled columns to data cells. A data row may have
        # one extra leading cell (the unlabelled select checkbox) vs the headers.
        if self._headers:
            offset = 1 if len(cells) == len(self._headers) + 1 else 0
            mapped: dict[str, str] = {}
            for index, field in enumerate(self._headers):
                if field is None:
                    continue
                cell_index = index + offset
                if 0 <= cell_index < len(cells) and cells[cell_index]:
                    mapped.setdefault(field, cells[cell_index])
            if "parcel" in mapped:
                return mapped
        # Fallback: classic positional order on the non-empty cells.
        nonempty = [cell for cell in cells if cell]
        if len(nonempty) < 3:
            return None
        mapped = {"parcel": nonempty[0], "address": nonempty[1], "owner": nonempty[2]}
        if len(nonempty) > 3:
            mapped["legal"] = nonempty[3]
        return mapped

    def _finish_row(self) -> None:
        mapped = self._map_columns(self._cells)
        if not mapped:
            return
        parcel_id = mapped["parcel"]
        compact = _compact_parcel_id(
            parcel_id,
            numeric_only=self._numeric_parcel_ids,
            preserve_whitespace=self._preserve_parcel_whitespace,
        )
        jurisdiction, tax_year = _parse_parcel_token(
            self._parcel_token, numeric_only=self._numeric_parcel_ids
        )
        hit = IasWorldAuditorSearchHit(
            parcel_id=parcel_id,
            parcel_number=compact,
            parcel_token=self._parcel_token,
            jurisdiction=jurisdiction,
            tax_year=tax_year,
            address=mapped.get("address"),
            owner=mapped.get("owner"),
            legal_description=mapped.get("legal"),
            raw_cells=[cell for cell in self._cells if cell],
        )
        self.rows.append(hit)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_TableCapture] = []
        self._stack: list[_TableCapture] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._stack.append(_TableCapture(_attrs(attrs)))
        elif tag == "tr" and self._stack:
            self._stack[-1].current_row = []
        elif tag in {"td", "th"} and self._stack and self._stack[-1].current_row is not None:
            self._stack[-1].current_cell = []
        elif tag == "br" and self._stack and self._stack[-1].current_cell is not None:
            self._stack[-1].current_cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1].current_cell is not None:
            self._stack[-1].current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        current = self._stack[-1]
        if tag in {"td", "th"} and current.current_cell is not None:
            current.current_row = current.current_row or []
            current.current_row.append(_clean_text(" ".join(current.current_cell)))
            current.current_cell = None
        elif tag == "tr" and current.current_row is not None:
            if any(cell for cell in current.current_row):
                current.rows.append(current.current_row)
            current.current_row = None
        elif tag == "table":
            self.tables.append(self._stack.pop())


class IasWorldAuditorClient:
    """Generic scraper for a Tyler iasWorld county auditor/property site.

    All site-specific behavior (base URL, ``jur`` district code, the ``mode=``
    search value) is supplied via :class:`IasWorldSiteConfig`; the search-form
    submission and datalet parsing are identical across iasWorld counties.
    """

    def __init__(
        self,
        config: IasWorldSiteConfig,
        *,
        timeout: float = 30.0,
        opener: Any | None = None,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._opener = opener or build_opener(HTTPCookieProcessor())

    @property
    def base_url(self) -> str:
        return self.config.base_url

    def search(self, query: IasWorldAuditorSearchQuery) -> IasWorldAuditorSearchResponse:
        query = IasWorldAuditorSearchQuery.model_validate(query)
        attempts = self._search_attempts(query)
        warnings: list[str] = []
        hits: list[IasWorldAuditorSearchHit] = []
        search_url = self.config.search_url(query.mode)
        site_year: str | None = None

        for fields, sort_by in attempts:
            html, final_url, form_site_year = self._submit_search(query, fields, sort_by)
            site_year = site_year or form_site_year
            parsed_hits = self._parse_search_results(html)
            if parsed_hits:
                hits = self._rank_hits(query, parsed_hits)[: query.max_results]
                break

            detail = self._parse_detail_if_present(html, final_url)
            if detail and detail.parcel_number:
                hits = [
                    IasWorldAuditorSearchHit(
                        parcel_id=detail.parcel_id,
                        parcel_number=detail.parcel_number,
                        parcel_token=detail.parcel_token,
                        jurisdiction=detail.jurisdiction,
                        tax_year=detail.tax_year,
                        address=detail.site_address,
                        owner=detail.owner_display,
                        detail_url=detail.source_url,
                    )
                ]
                details = [detail] if query.include_details else []
                warnings.extend(detail.warnings)
                return IasWorldAuditorSearchResponse(
                    query=query,
                    search_url=search_url,
                    search_mode=query.mode,
                    result_count=len(hits),
                    results=hits,
                    details=details,
                    warnings=warnings,
                )

        details: list[IasWorldAuditorParcelDetail] = []
        if query.include_details and query.max_detail_records > 0:
            for hit in hits[: query.max_detail_records]:
                try:
                    detail_url = self.detail_url_for_hit(hit, site_year)
                    if not detail_url:
                        continue
                    detail_html, final_url = self._get(detail_url)
                    detail = self.parse_detail(detail_html, source_url=final_url)
                    if not is_datalet_shaped(detail):
                        # Served 200 but is not a datalet: maintenance notice,
                        # bot block or error page. Reporting its empty fields as
                        # the parcel's would be worse than reporting nothing.
                        warnings.append(
                            f"{self.config.name} returned no readable datalet at "
                            f"{final_url} (site maintenance or bot protection?); "
                            f"detail omitted for parcel {hit.parcel_number}."
                        )
                        continue
                    warnings.extend(detail.warnings)
                    details.append(detail)
                    hit.detail_url = final_url
                except IasWorldAuditorClientError as exc:
                    warnings.append(str(exc))

        return IasWorldAuditorSearchResponse(
            query=query,
            search_url=search_url,
            search_mode=query.mode,
            result_count=len(hits),
            results=hits,
            details=details,
            warnings=warnings,
        )

    def detail_url(
        self,
        *,
        parcel_number: str,
        jurisdiction: str | None = None,
        tax_year: str | int | None = None,
    ) -> str:
        params: dict[str, str] = {
            "mode": "",
            "UseSearch": "no",
            "pin": _compact_parcel_id(
                parcel_number,
                numeric_only=self.config.numeric_parcel_ids,
                preserve_whitespace=self.config.preserve_parcel_whitespace,
            ),
            "jur": jurisdiction or self.config.district_code,
        }
        if tax_year:
            params["taxyr"] = str(tax_year)
        return f"{self.config.base_url}Datalets/Datalet.aspx?{urlencode(params)}"

    def detail_url_for_hit(
        self,
        hit: IasWorldAuditorSearchHit,
        site_year: str | None = None,
    ) -> str | None:
        jurisdiction, parcel_number, tax_year = _parse_parcel_token_full(
            hit.parcel_token, numeric_only=self.config.numeric_parcel_ids
        )
        parcel_number = parcel_number or hit.parcel_number
        if not parcel_number:
            return None
        return self.detail_url(
            parcel_number=parcel_number,
            jurisdiction=jurisdiction or self.config.district_code,
            tax_year=tax_year or site_year,
        )

    def parse_detail(
        self,
        html: str,
        *,
        source_url: str | None = None,
    ) -> IasWorldAuditorParcelDetail:
        parser = _TableParser()
        parser.feed(html)
        table_by_id = {
            _normalize_section_id(table.attrs["id"]): table
            for table in parser.tables
            if table.attrs.get("id") and table.rows
        }
        header = next(
            (
                table
                for table in parser.tables
                if "DataletHeader" in table.attrs.get("class", "")
            ),
            None,
        )
        header_data = _parse_header_table(header)

        raw_section_rows = {
            section_id: table.rows
            for section_id, table in table_by_id.items()
            if _is_data_section(section_id, table.rows)
        }
        sections = {
            section_id: _section_payload(rows)
            for section_id, rows in raw_section_rows.items()
        }

        parcel_number = _compact_parcel_id(
            header_data.get("parcel_id"), numeric_only=self.config.numeric_parcel_ids
        )
        if not parcel_number:
            parcel_number = _hidden_input_value(html, "hdPin")
        jurisdiction = _hidden_input_value(html, "hdJur") or _hidden_input_value(html, "hdXJur")
        tax_year = _hidden_input_value(html, "hdTaxYear") or _hidden_input_value(html, "hdXTaxYr")
        parcel_token = _parcel_token(jurisdiction, parcel_number, tax_year)

        if self.config.detail_profile in PUBLIC_ACCESS_LAYOUTS:
            profile_fields = _detail_fields_public_access(
                raw_section_rows,
                tax_year=tax_year,
                layout=PUBLIC_ACCESS_LAYOUTS[self.config.detail_profile],
            )
        elif self.config.detail_profile == DetailProfile.LAKE:
            profile_fields = _detail_fields_lake(raw_section_rows, tax_year=tax_year)
        else:
            profile_fields = _detail_fields_classic(raw_section_rows)

        return IasWorldAuditorParcelDetail(
            parcel_id=header_data.get("parcel_id"),
            parcel_number=parcel_number,
            parcel_token=parcel_token,
            jurisdiction=jurisdiction,
            tax_year=tax_year,
            map_routing=header_data.get("map_routing"),
            owner_display=header_data.get("owner"),
            site_address=header_data.get("address"),
            sections=sections,
            raw_section_rows=raw_section_rows,
            warnings=_profile_mismatch_warnings(
                raw_section_rows,
                profile_fields,
                profile=self.config.detail_profile,
                owner_display=header_data.get("owner"),
                source_url=source_url,
            ),
            source_url=source_url,
            **profile_fields,
        )

    def _submit_search(
        self,
        query: IasWorldAuditorSearchQuery,
        fields: dict[str, str],
        sort_by: str,
    ) -> tuple[str, str, str | None]:
        search_url = self.config.search_url(query.mode)
        form_html, _ = self._get(search_url)
        form_data, site_year = self._parse_form(form_html)
        page_size = _allowed_page_size(query.page_size)
        form_data.update(
            {
                "PageNum": str(query.page_number),
                "SortBy": sort_by,
                "SortDir": " asc",
                "PageSize": str(page_size),
                "selSortBy": sort_by,
                "selSortDir": " asc",
                "selPageSize": str(page_size),
                "hdAction": "Search",
            }
        )
        form_data.update(self._apply_field_overrides(fields))
        return (*self._post(search_url, form_data, referer=search_url), site_year)

    def _apply_field_overrides(self, fields: dict[str, str]) -> dict[str, str]:
        """Rename POST field keys for sites whose form labels differ.

        Most iasWorld counties share the classic field names; Lake's unified
        ``realprop`` form uses ``inpNo``/``inpOwner1`` instead of
        ``inpNumber``/``inpOwner``. With no overrides the dict is unchanged.
        """
        overrides = self.config.form_field_overrides
        if not overrides:
            return fields
        return {overrides.get(key, key): value for key, value in fields.items()}

    def _get(self, url: str) -> tuple[str, str]:
        return self._request(url)

    def _post(
        self,
        url: str,
        data: dict[str, str],
        *,
        referer: str | None = None,
    ) -> tuple[str, str]:
        encoded = urlencode(data).encode()
        return self._request(url, data=encoded, referer=referer)

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        referer: str | None = None,
    ) -> tuple[str, str]:
        headers = {
            "User-Agent": (
                f"Mozilla/5.0 (compatible; TitleMCP/0.1; +{self.config.base_url})"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if referer:
            headers["Referer"] = referer
        request = Request(url, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return body, response.geturl()
        except HTTPError as exc:
            raise IasWorldAuditorClientError(f"iasWorld request failed: {exc}") from exc
        except URLError as exc:
            raise IasWorldAuditorClientError(f"iasWorld request failed: {exc}") from exc

    def _parse_form(self, html: str) -> tuple[dict[str, str], str | None]:
        parser = _FormParser()
        parser.feed(html)
        site_year_match = re.search(r'var\s+siteYear\s*=\s*"([^"]+)"', html)
        return parser.form_data, site_year_match.group(1) if site_year_match else None

    def _parse_search_results(self, html: str) -> list[IasWorldAuditorSearchHit]:
        parser = _SearchResultsParser(
            numeric_parcel_ids=self.config.numeric_parcel_ids,
            preserve_parcel_whitespace=self.config.preserve_parcel_whitespace,
        )
        parser.feed(html)
        for hit in parser.rows:
            if not hit.detail_url:
                hit.detail_url = self.detail_url_for_hit(hit)
        return parser.rows

    def _parse_detail_if_present(
        self,
        html: str,
        final_url: str,
    ) -> IasWorldAuditorParcelDetail | None:
        if "DataletHeader" not in html:
            return None
        detail = self.parse_detail(html, source_url=final_url)
        return detail if detail.parcel_number else None

    def _search_attempts(
        self,
        query: IasWorldAuditorSearchQuery,
    ) -> list[tuple[dict[str, str], str]]:
        if query.mode == AuditorSearchMode.OWNER:
            return _dedupe_attempts(_owner_attempts(query))
        if query.mode == AuditorSearchMode.PARCEL_ID:
            return _dedupe_attempts(
                _parcel_attempts(
                    query,
                    numeric_parcel_ids=self.config.numeric_parcel_ids,
                    preserve_whitespace=self.config.preserve_parcel_whitespace,
                )
            )
        return _dedupe_attempts(_address_attempts(query))

    def _rank_hits(
        self,
        query: IasWorldAuditorSearchQuery,
        hits: list[IasWorldAuditorSearchHit],
    ) -> list[IasWorldAuditorSearchHit]:
        return sorted(
            hits,
            key=lambda hit: _hit_rank(
                query, hit, numeric_parcel_ids=self.config.numeric_parcel_ids
            ),
        )


def _address_attempts(
    query: IasWorldAuditorSearchQuery,
) -> list[tuple[dict[str, str], str]]:
    number, direction, street, unit = _address_parts(query)
    if not street:
        raise IasWorldAuditorClientError("Address searches require street_name or address.")

    base = {
        "inpAdrdir": direction or "",
        "inpStreet": street,
        "inpUnit": unit or "",
    }
    attempts: list[tuple[dict[str, str], str]] = []
    if number:
        attempts.append(({**base, "inpNumber": number}, "FULLADD"))
        if len(number) >= 3:
            attempts.append(({**base, "inpNumber": number[:-1]}, "FULLADD"))
    attempts.append(({**base, "inpNumber": ""}, "FULLADD"))
    return attempts


def _owner_attempts(
    query: IasWorldAuditorSearchQuery,
) -> list[tuple[dict[str, str], str]]:
    owner_name = query.owner_name or ""
    if not owner_name:
        raise IasWorldAuditorClientError("Owner searches require owner_name.")
    attempts = [({"inpOwner": owner_name}, "PARID")]
    first_token = re.split(r"\s+", owner_name.strip())[0]
    if len(first_token) >= 4:
        attempts.append(({"inpOwner": f"{first_token[:3]}*"}, "PARID"))
    return attempts


def _parcel_attempts(
    query: IasWorldAuditorSearchQuery,
    *,
    numeric_parcel_ids: bool = True,
    preserve_whitespace: bool = False,
) -> list[tuple[dict[str, str], str]]:
    parcel_id = query.parcel_id or ""
    if not parcel_id:
        raise IasWorldAuditorClientError("Parcel ID searches require parcel_id.")
    compact = _compact_parcel_id(
        parcel_id,
        keep_wildcards=True,
        numeric_only=numeric_parcel_ids,
        preserve_whitespace=preserve_whitespace,
    )
    attempts = [({"inpParid": compact}, "PARID")]
    if not numeric_parcel_ids:
        # Digit-slice wildcard fallbacks only make sense for numeric parcels.
        return attempts
    digits = _compact_parcel_id(parcel_id)
    if "*" not in compact and len(digits) >= 9:
        attempts.append(({"inpParid": f"{digits[:3]}*{digits[6:9]}"}, "PARID"))
    if "*" not in compact and len(digits) >= 6:
        attempts.append(({"inpParid": f"{digits[:6]}*"}, "PARID"))
    return attempts


def _address_parts(query: IasWorldAuditorSearchQuery) -> tuple[str, str, str, str]:
    number = str(query.address_number or "").strip()
    direction = (query.street_direction or "").strip().upper()
    street = query.street_name or ""
    unit = query.unit or ""
    if (not number or not street) and query.address:
        parsed_number, parsed_direction, parsed_street, parsed_unit = _parse_address(query.address)
        number = number or parsed_number
        direction = direction or parsed_direction
        street = street or parsed_street
        unit = unit or parsed_unit
    return number, direction, _street_without_suffix(street).upper(), unit


def _parse_address(address: str) -> tuple[str, str, str, str]:
    tokens = re.split(r"\s+", address.replace(",", " ").strip())
    if not tokens:
        return "", "", "", ""
    number = tokens[0] if re.match(r"^\d+", tokens[0]) else ""
    rest = tokens[1:] if number else tokens
    direction = ""
    if rest and rest[0].upper() in {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}:
        direction = rest.pop(0).upper()
    unit = ""
    for marker in ("APT", "UNIT", "#"):
        if marker in [token.upper() for token in rest]:
            idx = [token.upper() for token in rest].index(marker)
            if idx + 1 < len(rest):
                unit = rest[idx + 1]
            rest = rest[:idx]
            break
    return number, direction, _street_without_suffix(" ".join(rest)).upper(), unit


def _street_without_suffix(street: str) -> str:
    suffixes = {
        "ALY",
        "AVE",
        "AV",
        "BLVD",
        "CIR",
        "CT",
        "DR",
        "HWY",
        "LN",
        "PKWY",
        "PL",
        "RD",
        "ST",
        "TER",
        "TRL",
        "WAY",
    }
    tokens = re.split(r"\s+", street.strip())
    while tokens and tokens[-1].upper().rstrip(".") in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _dedupe_attempts(
    attempts: list[tuple[dict[str, str], str]]
) -> list[tuple[dict[str, str], str]]:
    seen: set[tuple[tuple[tuple[str, str], ...], str]] = set()
    deduped: list[tuple[dict[str, str], str]] = []
    for fields, sort_by in attempts:
        key = (tuple(sorted(fields.items())), sort_by)
        if key not in seen:
            seen.add(key)
            deduped.append((fields, sort_by))
    return deduped


def _hit_rank(
    query: IasWorldAuditorSearchQuery,
    hit: IasWorldAuditorSearchHit,
    *,
    numeric_parcel_ids: bool = True,
) -> tuple[int, str]:
    score = 10
    if query.parcel_id:
        wanted = _compact_parcel_id(query.parcel_id, numeric_only=numeric_parcel_ids)
        if hit.parcel_number == wanted:
            score = 0
    if query.mode == AuditorSearchMode.ADDRESS and hit.address:
        address_number, _direction, street_name, _unit = _address_parts(query)
        if address_number and hit.address.upper().startswith(address_number.upper()):
            score = min(score, 1)
        if street_name and street_name in hit.address.upper():
            score = min(score, 2)
    if query.owner_name and hit.owner:
        tokens = [token for token in re.split(r"\s+", query.owner_name.upper()) if len(token) > 1]
        if tokens and all(token.replace("*", "") in hit.owner.upper() for token in tokens):
            score = min(score, 1)
    return score, hit.parcel_number or ""


def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {key.lower(): value or "" for key, value in attrs}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _compact_parcel_id(
    value: str | None,
    *,
    keep_wildcards: bool = False,
    numeric_only: bool = True,
    preserve_whitespace: bool = False,
) -> str:
    if not value:
        return ""
    if numeric_only:
        pattern = r"[^0-9*]" if keep_wildcards else r"\D"
        return re.sub(pattern, "", value)
    # Alphanumeric parcels (e.g. Clermont "100200C003D", "100200.034C"): drop dash
    # separators but preserve letters, digits, and dots. By default whitespace is
    # also dropped; counties whose parcel form expects significant internal spaces
    # (Montgomery "A01 00000 0001") set preserve_whitespace=True.
    if preserve_whitespace:
        cleaned = re.sub(r"-", "", value)
        cleaned = re.sub(r"[^0-9A-Za-z.* ]", "", cleaned).upper()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
    else:
        cleaned = re.sub(r"[\s-]", "", value)
        cleaned = re.sub(r"[^0-9A-Za-z.*]", "", cleaned).upper()
    if not keep_wildcards:
        cleaned = cleaned.replace("*", "")
    return cleaned


def _allowed_page_size(value: int) -> int:
    if value <= 15:
        return 15
    if value <= 25:
        return 25
    return 50


def _looks_like_parcel_token(value: str) -> bool:
    return bool(re.match(r"^\d{3}:[0-9A-Za-z.*:-]+:\d{4}$", value))


def _parse_parcel_token(
    value: str | None,
    *,
    numeric_only: bool = True,
) -> tuple[str | None, str | None]:
    jurisdiction, _parcel_number, tax_year = _parse_parcel_token_full(
        value, numeric_only=numeric_only
    )
    return jurisdiction, tax_year


def _parse_parcel_token_full(
    value: str | None,
    *,
    numeric_only: bool = True,
) -> tuple[str | None, str | None, str | None]:
    if not value:
        return None, None, None
    parts = value.split(":")
    if len(parts) >= 3:
        parcel = _compact_parcel_id(parts[1], numeric_only=numeric_only) or None
        return parts[0] or None, parcel, parts[2] or None
    return None, None, None


def _parcel_token(
    jurisdiction: str | None,
    parcel_number: str | None,
    tax_year: str | None,
) -> str | None:
    if not all([jurisdiction, parcel_number, tax_year]):
        return None
    return f"{jurisdiction}:{parcel_number}:{tax_year}"


def _parse_header_table(table: _TableCapture | None) -> dict[str, str]:
    if not table or len(table.rows) < 2:
        return {}
    top = table.rows[0]
    bottom = table.rows[1]
    data: dict[str, str] = {}
    if top:
        data["parcel_id"] = _strip_label(top[0], "Parcel ID:")
    if len(top) > 1:
        data["map_routing"] = _strip_label(top[1], "Map Routing:")
    if bottom:
        data["owner"] = bottom[0]
    if len(bottom) > 1:
        data["address"] = bottom[1]
    return data


def _strip_label(value: str, label: str) -> str:
    return value.replace(label, "", 1).strip() if value.startswith(label) else value


def _is_data_section(section_id: str, rows: list[list[str]]) -> bool:
    if not rows:
        return False
    ignored = {"Table1"}
    return section_id not in ignored


def _section_payload(rows: list[list[str]]) -> dict[str, Any]:
    if not rows:
        return {}
    if len(rows[0]) == 2:
        return {"fields": _kv_section(rows), "rows": rows}
    return {"table": _table_section(rows), "rows": rows}


def _kv_section(rows: list[list[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    last_key: str | None = None
    for row in rows:
        if len(row) < 2:
            continue
        key = row[0].strip()
        value = row[1].strip()
        if not value:
            continue
        if not key:
            if last_key:
                _append_value(result, last_key, value)
            continue
        _append_value(result, key, value)
        last_key = key
    return result


def _append_value(result: dict[str, Any], key: str, value: str) -> None:
    existing = result.get(key)
    if existing is None:
        result[key] = value
    elif isinstance(existing, list):
        existing.append(value)
    else:
        result[key] = [existing, value]


def _table_section(rows: list[list[str]]) -> dict[str, Any]:
    if not rows:
        return {}
    headers = rows[0]
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        records.append(dict(zip(headers, padded, strict=False)))
    return {"headers": headers, "rows": records}


def _detail_fields_classic(raw_section_rows: dict[str, list[list[str]]]) -> dict[str, Any]:
    """Field extraction for the Franklin-style combined-``Owner`` datalet layout."""
    owner_section = _kv_section(raw_section_rows.get("Owner", []))
    transfer = _kv_section(raw_section_rows.get("Most Recent Transfer", []))
    tax_status_title = _section_name_ending(raw_section_rows, "Tax Status")
    tax_status = _kv_section(raw_section_rows.get(tax_status_title, []))
    appraised_title = _appraised_value_section_name(raw_section_rows)
    taxable_title = _section_name_containing(raw_section_rows, "Taxable Value")
    mailing_address = [
        value
        for value in [
            _string_or_none(owner_section.get("Owner Mailing /")),
            _string_or_none(
                _without_correction_request_values(owner_section.get("Contact Address"))
            ),
        ]
        if value
    ]
    site_property_address = _string_or_none(
        _without_correction_request_values(owner_section.get("Site (Property) Address"))
    )
    return {
        "permalink": _extract_first_url(_as_list(owner_section.get("Parcel Permalink"))),
        "owners": _as_list(owner_section.get("Owner")),
        "owner_mailing_address": mailing_address,
        "site_property_address": site_property_address,
        "legal_description": _as_list(owner_section.get("Legal Description")),
        "legal_acres": _string_or_none(owner_section.get("Legal Acres")),
        "most_recent_transfer": transfer,
        "tax_status": tax_status,
        "appraised_value": _table_section(raw_section_rows.get(appraised_title, [])),
        "taxable_value": _table_section(raw_section_rows.get(taxable_title, [])),
        "annual_taxes": _table_section(raw_section_rows.get("Annual Taxes", [])),
        "dwelling_data": _table_section(raw_section_rows.get("Dwelling Data", [])),
        "site_data": _table_section(raw_section_rows.get("Site Data", [])),
    }


def is_datalet_shaped(detail: IasWorldAuditorParcelDetail) -> bool:
    """Whether a parsed page looks like a datalet at all.

    A maintenance notice, a bot-block interstitial or an error page is served
    with HTTP 200 and parses without raising, yielding a detail with no data
    sections and no parcel number. That is indistinguishable from a real datalet
    unless it is checked for, so callers use this to drop the hollow record and
    say the page was unreadable instead of reporting empty fields as fact.
    """
    return bool(detail.raw_section_rows or detail.parcel_number)


def _profile_mismatch_warnings(
    raw_section_rows: dict[str, list[list[str]]],
    profile_fields: dict[str, Any],
    *,
    profile: DetailProfile,
    owner_display: str | None,
    source_url: str | None,
) -> list[str]:
    """Warn when a datalet parsed but the profile recognized none of its tables.

    A county that renames its datalet tables still parses cleanly: the sections
    are all there, the profile just matches none of them and every field it
    populates comes back empty. Nothing raises, so without this the caller sees
    a well-formed record with a blank owner and reads it as fact. Identity
    fields are the tell, since a datalet always names an owner somewhere.
    """
    if not raw_section_rows:
        return []
    layout = PUBLIC_ACCESS_LAYOUTS.get(profile)
    if layout is None:
        expected = ("owners", "owner_mailing_address", "legal_description")
    else:
        # Only fields this layout says its datalet carries can count as a miss.
        # Lucas's tab genuinely serves no owner, mailing address or legal
        # description, so an empty one there is the page, not a bad profile.
        expected = tuple(
            field
            for field, source in (
                ("owners", layout.owner),
                ("owner_mailing_address", layout.mailing),
                ("legal_description", layout.legal),
            )
            if source.declared
        )
    if not expected:
        return []
    if any(profile_fields.get(field) for field in expected):
        return []
    # The header table carries the owner independently of the profile, so its
    # presence means the page really is a populated parcel and only the
    # profile's section names missed.
    hint = " (the page has an owner in its header)" if owner_display else ""
    where = f" at {source_url}" if source_url else ""
    return [
        f"detail_profile={profile.value} matched none of the datalet sections"
        f"{where}{hint}; owner, mailing address and legal description are empty. "
        f"Sections served: {', '.join(sorted(raw_section_rows))}."
    ]


class LabelStyle(StrEnum):
    """How a datalet table labels the values inside it.

    The section *names* vary between counties, and so does the labelling
    *within* a section. These are the three shapes seen so far, and they are
    what let one extractor read every variant.
    """

    # "Owner 1", "Address 1", "Legal Desc 1" (Clermont, Butler).
    NUMBERED = "numbered"
    # "Mailing Address" -> value, where a blank label continues the line above
    # (Montgomery's multi-line owner names and legal descriptions).
    KEYED = "keyed"
    # A one-column table: a header cell, then one value cell per row
    # (Montgomery's "Owner" table, whose only header is "Name").
    COLUMN = "column"


@dataclass(frozen=True)
class FieldSource:
    """Where one canonical field lives on a datalet, and how it is labelled.

    An empty ``sections`` means this layout's datalet does not carry the field
    at all, which is different from carrying it and failing to read it. Only a
    declared source counts as a miss when nothing comes back, so a county whose
    tab genuinely has no owner is not reported as a broken profile.
    """

    sections: tuple[str, ...] = ()
    style: LabelStyle = LabelStyle.NUMBERED
    labels: tuple[str, ...] = ()

    @property
    def declared(self) -> bool:
        return bool(self.sections)


@dataclass(frozen=True)
class PublicAccessLayout:
    """Which datalet tables and labels one iasWorld variant uses.

    Counties serve the same fields under different table names and different
    labelling, so a variant is an entry in ``PUBLIC_ACCESS_LAYOUTS`` rather than
    a new profile function. Each ``sections`` tuple is tried in order and the
    first table present on the page wins, so a variant only has to name what it
    calls differently.
    """

    parcel_sections: tuple[str, ...] = ("Parcel",)
    owner: FieldSource = FieldSource(("Owner",), LabelStyle.NUMBERED, ("Owner",))
    mailing: FieldSource = FieldSource(
        ("Tax Mailing Name and Address",), LabelStyle.NUMBERED, ("Address",)
    )
    legal: FieldSource = FieldSource(("Legal",), LabelStyle.NUMBERED, ("Legal Desc",))
    parcel_labels: tuple[tuple[str, str], ...] = (
        ("Class", "Property Class"),
        ("Land Use Code", "Land Use"),
        ("Neighborhood", "Appraisal Neighborhood"),
    )
    address_label: str = "Address"
    acres_label: str = "Total Acres"
    charged_sections: tuple[str, ...] = ("Taxes Charged",)
    charged_style: str = "total_charged"
    value_sections: tuple[str, ...] = ()
    value_style: str = "kv"
    appraised_labels: tuple[str, str, str] | None = None
    taxable_labels: tuple[str, str, str] | None = None
    appraised_column: str | None = None
    taxable_column: str | None = None
    transfer_sections: tuple[str, ...] = ()
    transfer_style: str = "table_newest_first"
    transfer_date_label: str = "Date"
    transfer_price_label: str = "Sale Amount"
    dwelling_sections: tuple[str, ...] = ()
    # Source label -> the canonical column the classic "Dwelling Data" table uses,
    # so the canonical mapper stays profile-agnostic.
    dwelling_labels: tuple[tuple[str, str], ...] = ()
    # One label whose value packs several counts in order, e.g. Montgomery's
    # "Total Rms/Bedrms/Baths/Half Baths" -> "9/4/2/1".
    dwelling_combined: tuple[str, tuple[str, ...]] | None = None


PUBLIC_ACCESS_LAYOUTS: dict[DetailProfile, PublicAccessLayout] = {
    # Clermont: the original split-section Public Access datalet.
    DetailProfile.PUBLIC_ACCESS: PublicAccessLayout(),
    # Butler: same numbered labels, but owner and legal share one table, the
    # mailing table is named for the tax bill, and it additionally serves value,
    # transfer and half-year tax tables the plain variant has no equivalent for.
    DetailProfile.PUBLIC_ACCESS_DETAILED: PublicAccessLayout(
        owner=FieldSource(("Owner and Legal", "Owner"), LabelStyle.NUMBERED, ("Owner",)),
        legal=FieldSource(("Owner and Legal", "Legal"), LabelStyle.NUMBERED, ("Legal",)),
        mailing=FieldSource(
            ("Taxbill Mailing Address", "Tax Mailing Name and Address"),
            LabelStyle.NUMBERED,
            ("Address",),
        ),
        parcel_labels=(
            ("Class", "Property Class"),
            ("Land Use Code", "Land Use"),
            ("Neighborhood", "Appraisal Neighborhood"),
            ("Taxing District", "Tax District"),
            ("District Name", "School District"),
        ),
        charged_sections=("Current Year Real Estate Taxes",),
        charged_style="half_year",
        value_sections=("Current Value",),
        appraised_labels=("Land (100%)", "Building (100%)", "Total Value (100%)"),
        taxable_labels=("Land (35%)", "Building (35%)", "Assessed Total (35%)"),
        transfer_sections=("Transfers",),
        dwelling_sections=("Dwelling",),
        dwelling_labels=(
            ("Year Built", "Yr Built"),
            ("Total Living Area (Sq. Ft.)", "Tot Fin Area"),
            ("Bedrooms", "Bedrooms"),
            ("Full Baths", "Full Baths"),
            ("Half Baths", "Half Baths"),
        ),
    ),
    # Montgomery: split sections again, but labelled rather than numbered. Its
    # owner table is a single column under a "Name" header, and multi-line
    # values continue on rows whose label cell is blank. Its "Sales" table is
    # oldest first, unlike Butler's.
    DetailProfile.PUBLIC_ACCESS_KEYED: PublicAccessLayout(
        parcel_sections=("Legal",),
        owner=FieldSource(("Owner",), LabelStyle.COLUMN, ("Name",)),
        mailing=FieldSource(
            ("Mailing",), LabelStyle.KEYED, ("Mailing Address", "City, State, Zip")
        ),
        legal=FieldSource(("Legal",), LabelStyle.KEYED, ("Legal Description",)),
        parcel_labels=(
            ("Land Use Description", "Land Use"),
            ("Tax District Name", "Tax District"),
        ),
        address_label="",
        acres_label="Acres",
        charged_sections=("Tax Summary",),
        charged_style="half_columns",
        transfer_sections=("Sales",),
        transfer_style="table_newest_last",
        transfer_price_label="Sale Price",
        dwelling_sections=("Building",),
        dwelling_labels=(
            ("Year Built", "Yr Built"),
            ("Total Square Footage", "Tot Fin Area"),
        ),
        dwelling_combined=(
            "Total Rms/Bedrms/Baths/Half Baths",
            ("Rooms", "Bedrooms", "Full Baths", "Half Baths"),
        ),
    ),
    # Lucas: a "Summary - " tabbed datalet. This tab carries no owner, mailing
    # address or legal description at all, so those sources stay undeclared and
    # the owner comes from the search hit. Its value table is transposed:
    # Land/Building/Total are rows and the valuation basis is the column.
    DetailProfile.SUMMARY_SECTIONS: PublicAccessLayout(
        parcel_sections=("Summary - General",),
        owner=FieldSource(),
        mailing=FieldSource(),
        legal=FieldSource(),
        parcel_labels=(
            ("Class", "Property Class"),
            ("Land Use", "Land Use"),
            ("Tax District", "Tax District"),
        ),
        address_label="",
        acres_label="",
        charged_sections=(),
        value_sections=("Summary - Values",),
        value_style="transposed",
        appraised_column="100% Values",
        taxable_column="35% Values",
        transfer_sections=("Summary - Most Recent Sale",),
        transfer_style="keyed",
        transfer_date_label="Sales Date",
    ),
}


def _detail_fields_public_access(
    raw_section_rows: dict[str, list[list[str]]],
    *,
    tax_year: str | None = None,
    layout: PublicAccessLayout | None = None,
) -> dict[str, Any]:
    """Field extraction for the iasWorld "Public Access" split-section layout.

    Normalizes into the same shape as the classic profile (and the same
    ``tax_status`` keys) so the canonical mapper stays profile-agnostic.
    """
    layout = layout or PUBLIC_ACCESS_LAYOUTS[DetailProfile.PUBLIC_ACCESS]
    parcel = _kv_section(_first_section(raw_section_rows, layout.parcel_sections))
    value_rows = _first_section(raw_section_rows, layout.value_sections)
    values = _kv_section(value_rows)

    mailing_lines = _field_values(raw_section_rows, layout.mailing)
    tax_status: dict[str, Any] = {}
    for source_label, canonical_label in layout.parcel_labels:
        value = _first_value(parcel.get(source_label))
        if value:
            tax_status[canonical_label] = value
    zip_code = _zip_from_lines(mailing_lines)
    if zip_code:
        tax_status["Zip Code"] = zip_code

    charged_rows = _first_section(raw_section_rows, layout.charged_sections)
    if layout.charged_style == "half_year":
        annual_taxes = _half_year_annual_taxes(charged_rows, tax_year)
    elif layout.charged_style == "half_columns":
        annual_taxes = _half_column_annual_taxes(charged_rows, tax_year)
    else:
        annual_taxes = _public_access_annual_taxes(charged_rows, tax_year)

    if layout.value_style == "transposed":
        appraised = _transposed_value_table(
            value_rows, layout.appraised_column, "Market (100%)"
        )
        taxable = _transposed_value_table(value_rows, layout.taxable_column, "Assessed (35%)")
    else:
        appraised = _kv_value_table(values, layout.appraised_labels, "Market (100%)")
        taxable = _kv_value_table(values, layout.taxable_labels, "Assessed (35%)")

    return {
        "permalink": None,
        "owners": _field_values(raw_section_rows, layout.owner),
        "owner_mailing_address": mailing_lines,
        "site_property_address": (
            _first_value(parcel.get(layout.address_label)) if layout.address_label else None
        ),
        "legal_description": _field_values(raw_section_rows, layout.legal),
        "legal_acres": (
            _first_value(parcel.get(layout.acres_label)) if layout.acres_label else None
        ),
        "most_recent_transfer": _layout_transfer(
            _first_section(raw_section_rows, layout.transfer_sections), layout
        ),
        "tax_status": tax_status,
        "appraised_value": appraised,
        "taxable_value": taxable,
        "annual_taxes": annual_taxes,
        "dwelling_data": _layout_dwelling(
            _first_section(raw_section_rows, layout.dwelling_sections), layout
        ),
        "site_data": {},
    }


def _layout_dwelling(rows: list[list[str]], layout: PublicAccessLayout) -> dict[str, Any]:
    """Normalize a key/value dwelling section into the classic one-row table."""
    if not rows:
        return {}
    kv = _kv_section(rows)
    row: dict[str, Any] = {}
    for source_label, canonical_label in layout.dwelling_labels:
        value = _first_value(kv.get(source_label))
        if value:
            row[canonical_label] = value
    if layout.dwelling_combined:
        source_label, canonical_labels = layout.dwelling_combined
        packed = _first_value(kv.get(source_label)) or ""
        parts = [part.strip() for part in packed.split("/")]
        for canonical_label, part in zip(canonical_labels, parts, strict=False):
            if part:
                row.setdefault(canonical_label, part)
    if not row:
        return {}
    return {"headers": list(row), "rows": [row]}


def _field_values(
    raw_section_rows: dict[str, list[list[str]]],
    source: FieldSource,
) -> list[str]:
    """Read one field's values however its layout labels them."""
    rows = _first_section(raw_section_rows, source.sections)
    if not rows:
        return []
    if source.style is LabelStyle.NUMBERED:
        kv = _kv_section(rows)
        values: list[str] = []
        for prefix in source.labels:
            values.extend(_numbered_values(kv, prefix))
        return values
    if source.style is LabelStyle.COLUMN:
        return _column_values(rows, source.labels)
    return _keyed_values(rows, source.labels)


def _keyed_values(rows: list[list[str]], labels: tuple[str, ...]) -> list[str]:
    """Values for labelled rows, following blank-label continuation rows.

    Montgomery writes a multi-line legal description as ``Legal Description`` on
    the first row and a blank label on the rest, so a continuation only counts
    while a wanted label is open.
    """
    wanted = {label.casefold() for label in labels}
    values: list[str] = []
    collecting = False
    for row in rows:
        if not row:
            continue
        label = (row[0] or "").strip()
        value = (row[1] or "").strip() if len(row) > 1 else ""
        if label:
            collecting = label.rstrip(":").casefold() in wanted
        if collecting and value:
            values.append(value)
    return values


def _column_values(rows: list[list[str]], headers: tuple[str, ...]) -> list[str]:
    """Values from a one-column table that starts with a header cell."""
    wanted = {header.casefold() for header in headers}
    values: list[str] = []
    started = False
    for row in rows:
        if not row:
            continue
        first = (row[0] or "").strip()
        if not started:
            started = len(row) == 1 and first.casefold() in wanted
            continue
        if len(row) != 1:
            break
        if first:
            values.append(first)
    return values


def _transposed_value_table(
    rows: list[list[str]],
    column: str | None,
    category: str,
) -> dict[str, Any]:
    """Reshape a value table whose basis is the column and Land/Total the rows."""
    if not column or not rows:
        return {}
    table = _table_section(rows)
    table_rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(table_rows, list):
        return {}
    by_label: dict[str, dict[str, Any]] = {}
    for row in table_rows:
        if not isinstance(row, dict):
            continue
        label = _string_or_none(row.get("")) or _string_or_none(row.get("Category"))
        if label:
            by_label[label.casefold()] = row

    def cell(label: str) -> str:
        row = by_label.get(label)
        return (_string_or_none(row.get(column)) or "") if row else ""

    land, improvements, total = cell("land"), cell("building"), cell("total")
    if not any((land, improvements, total)):
        return {}
    return {
        "headers": ["", "Land", "Improvements", "Total"],
        "rows": [
            {"": category, "Land": land, "Improvements": improvements, "Total": total}
        ],
    }


def _layout_transfer(rows: list[list[str]], layout: PublicAccessLayout) -> dict[str, Any]:
    """Most recent sale, however this layout orders and labels its sales table."""
    if not rows:
        return {}
    if layout.transfer_style == "keyed":
        kv = _kv_section(rows)
        date = _first_value(kv.get(layout.transfer_date_label))
        price = _first_value(kv.get(layout.transfer_price_label))
    else:
        table = _table_section(rows)
        table_rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(table_rows, list) or not table_rows:
            return {}
        # Butler lists newest first; Montgomery lists oldest first.
        row = table_rows[-1] if layout.transfer_style == "table_newest_last" else table_rows[0]
        date = _string_or_none(row.get(layout.transfer_date_label))
        price = _string_or_none(row.get(layout.transfer_price_label))
    transfer: dict[str, Any] = {}
    if date:
        transfer["Transfer Date"] = date
    if price:
        transfer["Transfer Price"] = price
    return transfer


def _half_column_annual_taxes(
    charged_rows: list[list[str]],
    tax_year: str | None,
) -> dict[str, Any]:
    """Normalize a half-year *column* tax table into the canonical annual row.

    Montgomery publishes the two half-year charges as columns rather than a
    precomputed annual total, so the halves are summed to get the year's charge
    and the payment columns are summed for what has been paid.
    """
    table = _table_section(charged_rows)
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[0]
    if not isinstance(row, dict):
        return {}
    charged = _sum_money(row.get("1st Half"), row.get("2nd Half"))
    if charged is None:
        return {}
    entry: dict[str, Any] = {
        "Tax Year": _string_or_none(row.get("Year")) or tax_year or "",
        "Net Annual Tax": charged,
    }
    paid = _sum_money(row.get("1st Half Payments"), row.get("2nd Half Payments"))
    if paid is not None:
        entry["Total Paid"] = paid.lstrip("-")
    return {"headers": list(entry), "rows": [entry]}


def _sum_money(*values: Any) -> str | None:
    """Add money-ish cells, keeping the comma/2dp shape the sites use."""
    total = Decimal(0)
    seen = False
    for value in values:
        text = _string_or_none(value)
        if not text:
            continue
        cleaned = text.replace("$", "").replace(",", "").strip()
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        try:
            total += Decimal(cleaned)
        except InvalidOperation:
            continue
        seen = True
    if not seen:
        return None
    return f"{total:,.2f}"


def _first_section(
    raw_section_rows: dict[str, list[list[str]]],
    names: tuple[str, ...],
) -> list[list[str]]:
    """Rows of the first named table the page actually serves."""
    for name in names:
        rows = raw_section_rows.get(name)
        if rows:
            return rows
    return []


def _kv_value_table(
    values: dict[str, Any],
    labels: tuple[str, str, str] | None,
    category: str,
) -> dict[str, Any]:
    """Reshape a key/value value table into the canonical Land/Improvements/Total row."""
    if not labels:
        return {}
    land, improvements, total = (_first_value(values.get(label)) for label in labels)
    if not any((land, improvements, total)):
        return {}
    return {
        "headers": ["", "Land", "Improvements", "Total"],
        "rows": [
            {
                "": category,
                "Land": land or "",
                "Improvements": improvements or "",
                "Total": total or "",
            }
        ],
    }



def _half_year_annual_taxes(
    charged_rows: list[list[str]],
    tax_year: str | None,
) -> dict[str, Any]:
    """Normalize a half-year tax table into the canonical annual-tax row.

    The table is charge-type rows (``Real Estate``, ``Special Assessments``,
    ``Tot Payments``) against half-year columns. Only the real estate charge and
    the payment total map onto the canonical fields; the untouched table stays
    available on the detail record.
    """
    table = _table_section(charged_rows)
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = _string_or_none(row.get("TAX TYPE"))
        if label:
            by_type[label.rstrip(":").strip().casefold()] = row
    charged = by_type.get("real estate")
    net_annual_tax = _string_or_none(charged.get("Total")) if charged else None
    if not net_annual_tax:
        return {}
    entry: dict[str, Any] = {"Tax Year": tax_year or "", "Net Annual Tax": net_annual_tax}
    payments = by_type.get("tot payments")
    total_paid = _string_or_none(payments.get("Total")) if payments else None
    if total_paid:
        entry["Total Paid"] = total_paid.lstrip("-")
    return {"headers": list(entry), "rows": [entry]}


def _detail_fields_lake(
    raw_section_rows: dict[str, list[list[str]]],
    *,
    tax_year: str | None = None,
) -> dict[str, Any]:
    """Field extraction for Lake County's datalet layout.

    Lake is a third iasWorld template. It differs from both other profiles in
    four ways, all confirmed against live parcels:

    - Section ids carry trailing anchor markup ("Owner Name and Mailing
      Address<a href=...>"), stripped by ``_normalize_section_id`` at parse
      time, so lookups here use the clean prefix.
    - Labels are singular (``Owner Name``, ``Legal Description``) rather than
      the Public Access numbered form (``Owner 1``, ``Legal Desc 1``).
    - Empty fields are written as ``-`` rather than left blank.
    - Value tables are prefixed and column-oriented (``Appraised Land`` /
      ``Appraised Building`` / ``Appraised Total``, keyed by ``Year``), so they
      are reshaped into the canonical Land/Improvements/Total rows.

    Lake serves no ``DataletHeader`` table, so ``site_property_address`` is not
    available on the detail page (the owner *mailing* address is not a reliable
    stand-in); the site address comes from the search hit instead. There is no
    transfer/sales section on this datalet tab, so ``most_recent_transfer`` is
    empty and remains a follow-up.
    """
    parcel = _lake_kv_section(raw_section_rows, "Parcel")
    owner = _lake_kv_section(raw_section_rows, "Owner Name and Mailing Address")
    legal = _lake_kv_section(raw_section_rows, "Legal Description Information")

    mailing_lines = [
        value
        for value in (
            _first_value(owner.get("Owner Mailing Address")),
            _first_value(owner.get("City, State, Zip")),
        )
        if value
    ]

    tax_status: dict[str, Any] = {}
    for source_label, canonical_label in (
        ("Class", "Property Class"),
        ("Land Use Code", "Land Use"),
        ("Neighborhood", "Appraisal Neighborhood"),
        ("Municipality", "City/Village"),
    ):
        value = _first_value(parcel.get(source_label))
        if value:
            tax_status[canonical_label] = value
    zip_code = _zip_from_lines(mailing_lines)
    if zip_code:
        tax_status["Zip Code"] = zip_code

    return {
        "permalink": None,
        "owners": _as_list(owner.get("Owner Name")),
        "owner_mailing_address": mailing_lines,
        "site_property_address": None,
        "legal_description": _as_list(legal.get("Legal Description")),
        "legal_acres": _first_value(parcel.get("Total Acres")),
        "most_recent_transfer": {},
        "tax_status": tax_status,
        "appraised_value": _lake_value_table(
            _lake_section_rows(raw_section_rows, "Appraised"), "Appraised"
        ),
        "taxable_value": _lake_value_table(
            _lake_section_rows(raw_section_rows, "Assessed Value"), "Assessed"
        ),
        "annual_taxes": _lake_annual_taxes(
            _lake_section_rows(raw_section_rows, "Taxes Due"), tax_year
        ),
        "dwelling_data": {},
        "site_data": {},
    }


def _lake_section_rows(
    raw_section_rows: dict[str, list[list[str]]],
    prefix: str,
) -> list[list[str]]:
    """Lake section ids are stable only up to their leading words."""
    for name, rows in raw_section_rows.items():
        if name.startswith(prefix):
            return rows
    return []


def _lake_kv_section(
    raw_section_rows: dict[str, list[list[str]]],
    prefix: str,
) -> dict[str, Any]:
    """Key/value section with Lake's ``-`` placeholders and label noise removed."""
    section = _kv_section(_lake_section_rows(raw_section_rows, prefix))
    cleaned: dict[str, Any] = {}
    for key, value in section.items():
        values = [item for item in _as_list(value) if item.strip(" -")]
        if not values:
            continue
        # "Land Use Code **" carries a footnote marker; the value repeats the
        # link text of the code-list anchor.
        clean_key = key.rstrip("* ").rstrip(":").strip()
        cleaned[clean_key] = [_lake_clean_value(item) for item in values]
    return {key: value[0] if len(value) == 1 else value for key, value in cleaned.items()}


def _lake_value_table(rows: list[list[str]], prefix: str) -> dict[str, Any]:
    """Reshape Lake's prefixed, year-keyed value table into canonical columns."""
    table = _table_section(rows)
    records = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(records, list):
        return {}
    value_rows = [
        {
            "Category": year,
            "Land": record.get(f"{prefix} Land", ""),
            "Improvements": record.get(f"{prefix} Building", ""),
            "Total": record.get(f"{prefix} Total", ""),
        }
        for record in records
        if isinstance(record, dict)
        and (year := _string_or_none(record.get("Year")))
        and year.isdigit()
    ]
    if not value_rows:
        return {}
    return {"headers": ["Category", "Land", "Improvements", "Total"], "rows": value_rows}


def _lake_annual_taxes(rows: list[list[str]], tax_year: str | None) -> dict[str, Any]:
    """Lake reports a ``Taxes Due`` roll-up rather than a per-year tax table."""
    table = _table_section(rows)
    records = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(records, list) or not records:
        return {}
    total = _string_or_none(records[0].get("Total"))
    if not total:
        return {}
    return {
        "headers": ["Tax Year", "Net Annual Tax"],
        "rows": [{"Tax Year": tax_year or "", "Net Annual Tax": total}],
    }


def _normalize_section_id(section_id: str) -> str:
    """Drop trailing markup some counties embed in the datalet section id."""
    return section_id.split("<", 1)[0].strip()


def _lake_clean_value(value: str) -> str:
    """Strip Lake's code-list link text and its dangling ``code -`` separator.

    Lake renders coded fields as ``<code> - <description>`` and leaves the
    separator in place when the description is empty (``01R04000 -``).
    """
    trimmed = _strip_suffix(value, "(Land Use Codes Descriptions)")
    return trimmed.rstrip("- ").strip() if trimmed.endswith("-") else trimmed


def _strip_suffix(value: str, suffix: str) -> str:
    trimmed = value.strip()
    if trimmed.endswith(suffix):
        return trimmed[: -len(suffix)].strip()
    return trimmed


def _numbered_values(kv: dict[str, Any], prefix: str) -> list[str]:
    """Collect values of numbered labels (``Owner 1``, ``Address 1`` …) in order."""
    pattern = re.compile(rf"^{re.escape(prefix)}\s+(\d+)$")
    numbered: list[tuple[int, str]] = []
    for key, value in kv.items():
        match = pattern.match(key)
        if not match:
            continue
        for item in _as_list(value):
            if item:
                numbered.append((int(match.group(1)), item))
    return [value for _index, value in sorted(numbered, key=lambda pair: pair[0])]


def _first_value(value: Any) -> str | None:
    """First non-empty value — Public Access cells sometimes carry trailing note rows."""
    if isinstance(value, list):
        return next((_string_or_none(item) for item in value if _string_or_none(item)), None)
    return _string_or_none(value)


def _zip_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"\b(\d{5})(?:-\d{4})?\b", line)
        if match:
            return match.group(1)
    return None


def _public_access_annual_taxes(
    charged_rows: list[list[str]],
    tax_year: str | None,
) -> dict[str, Any]:
    table = _table_section(charged_rows)
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    total_charged = _string_or_none(rows[0].get("Total Charged"))
    if not total_charged:
        return {}
    return {
        "headers": ["Tax Year", "Net Annual Tax"],
        "rows": [{"Tax Year": tax_year or "", "Net Annual Tax": total_charged}],
    }


def _section_name_ending(
    raw_section_rows: dict[str, list[list[str]]],
    suffix: str,
) -> str:
    return next((name for name in raw_section_rows if name.endswith(suffix)), "")


def _section_name_containing(
    raw_section_rows: dict[str, list[list[str]]],
    needle: str,
) -> str:
    return next((name for name in raw_section_rows if needle in name), "")


def _appraised_value_section_name(raw_section_rows: dict[str, list[list[str]]]) -> str:
    explicit = _section_name_containing(raw_section_rows, "Appraised Value")
    if explicit:
        return explicit
    return next(
        (
            name
            for name, rows in raw_section_rows.items()
            if "Auditor" in name and _looks_like_value_table(rows)
        ),
        "",
    )


def _looks_like_value_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    headers = [header.lower() for header in rows[0]]
    return "land" in headers and "improvements" in headers and "total" in headers


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _without_correction_request_values(value: Any) -> Any:
    values = _as_list(value)
    filtered = [item for item in values if "Correction Request" not in item]
    if not filtered:
        return None
    return filtered if len(filtered) > 1 else filtered[0]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value if str(item)) or None
    return str(value) or None


def _extract_first_url(values: list[str]) -> str | None:
    for value in values:
        match = re.search(r"https?://\S+", value)
        if match:
            return match.group(0)
    return None


def _hidden_input_value(html: str, input_id: str) -> str | None:
    pattern = (
        rf'<input[^>]+id=["\']{re.escape(input_id)}["\'][^>]*'
        rf'value=["\']([^"\']*)["\']'
    )
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if match:
        return match.group(1) or None
    pattern = (
        rf'<input[^>]+value=["\']([^"\']*)["\'][^>]*'
        rf'id=["\']{re.escape(input_id)}["\']'
    )
    match = re.search(pattern, html, flags=re.IGNORECASE)
    return match.group(1) if match else None

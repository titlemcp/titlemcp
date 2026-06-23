from __future__ import annotations

import re
from dataclasses import dataclass, field
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
            table.attrs["id"]: table
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

        if self.config.detail_profile == DetailProfile.PUBLIC_ACCESS:
            profile_fields = _detail_fields_public_access(raw_section_rows, tax_year=tax_year)
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


def _detail_fields_public_access(
    raw_section_rows: dict[str, list[list[str]]],
    *,
    tax_year: str | None = None,
) -> dict[str, Any]:
    """Field extraction for the iasWorld "Public Access" split-section layout.

    Normalizes into the same shape as the classic profile (and the same
    ``tax_status`` keys) so the canonical mapper stays profile-agnostic.
    """
    parcel = _kv_section(raw_section_rows.get("Parcel", []))
    owner = _kv_section(raw_section_rows.get("Owner", []))
    mailing = _kv_section(raw_section_rows.get("Tax Mailing Name and Address", []))
    legal = _kv_section(raw_section_rows.get("Legal", []))

    mailing_lines = _numbered_values(mailing, "Address")
    tax_status: dict[str, Any] = {}
    for source_label, canonical_label in (
        ("Class", "Property Class"),
        ("Land Use Code", "Land Use"),
        ("Neighborhood", "Appraisal Neighborhood"),
    ):
        value = _first_value(parcel.get(source_label))
        if value:
            tax_status[canonical_label] = value
    zip_code = _zip_from_lines(mailing_lines)
    if zip_code:
        tax_status["Zip Code"] = zip_code

    return {
        "permalink": None,
        "owners": _numbered_values(owner, "Owner"),
        "owner_mailing_address": mailing_lines,
        "site_property_address": _first_value(parcel.get("Address")),
        "legal_description": _numbered_values(legal, "Legal Desc"),
        "legal_acres": _first_value(parcel.get("Total Acres")),
        "most_recent_transfer": {},
        "tax_status": tax_status,
        "appraised_value": {},
        "taxable_value": {},
        "annual_taxes": _public_access_annual_taxes(
            raw_section_rows.get("Taxes Charged", []), tax_year
        ),
        "dwelling_data": {},
        "site_data": {},
    }


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

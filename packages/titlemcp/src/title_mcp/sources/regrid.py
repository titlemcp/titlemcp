from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field
from requests.adapters import HTTPAdapter
from requests.exceptions import ProxyError

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.auditor import MoneyAmount
from title_mcp.domain.models import Address, Jurisdiction
from title_mcp.domain.parcel import (
    ParcelBuilding,
    ParcelGeography,
    ParcelIdentifiers,
    ParcelLandUse,
    ParcelOwnership,
    ParcelRecord,
    ParcelRecordSource,
    ParcelSearchContext,
    ParcelSite,
    ParcelValuation,
)
from title_mcp.settings import TitleMCPSettings, get_settings
from title_mcp.sources.base import (
    SourceCitation,
    SourceConnector,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)

LOGGER = logging.getLogger(__name__)

_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
]


class RegridClientError(RuntimeError):
    pass


class RegridProxyConfigurationError(RegridClientError):
    pass


class RegridServiceUnavailableError(RegridClientError):
    pass


class RegridParcelLookupQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    address: str = Field(min_length=1)


class RegridParcelLookupRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.regrid_parcel_lookup"
    schema_version: str = "1.0"
    record_type: str = "parcel_lookup"
    source: dict[str, Any]
    query: dict[str, Any]
    label: str | None = None
    path: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class _RegridParcelServiceProtocol(Protocol):
    def lookup(self, address: str) -> RegridParcelLookupRecord | None:
        """Lookup parcel details for an address."""


def generate_regrid_headers() -> dict[str, str]:
    accept_options = [
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "text/html,application/xhtml+xml,application/xml;q=0.8,*/*;q=0.6",
        "text/html,application/xml;q=0.9,*/*;q=0.8",
    ]
    accept_encoding_options = [
        "gzip, deflate, br",
        "gzip, deflate",
        "gzip, deflate, br, zstd",
    ]
    sec_ua_platform_options = ['"Windows"', '"Linux"', '"macOS"']

    return {
        "accept": random.choice(accept_options),
        "accept-encoding": random.choice(accept_encoding_options),
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "priority": "u=0, i",
        "sec-ch-ua": (
            f'"Google Chrome";v="{random.randint(100, 140)}", '
            f'"Chromium";v="{random.randint(100, 140)}", '
            f'"Not_A Brand";v="{random.randint(20, 30)}"'
        ),
        "sec-ch-ua-mobile": random.choice(["?0", "?1"]),
        "sec-ch-ua-platform": random.choice(sec_ua_platform_options),
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": random.choice(["none", "same-origin"]),
        "sec-fetch-user": random.choice(["?1", "?0"]),
        "upgrade-insecure-requests": "1",
        "User-Agent": random.choice(_USER_AGENTS),
    }


class RegridParcelQueryService:
    def __init__(
        self,
        *,
        smart_proxy: str,
        proxy_port_start: int = 10001,
        proxy_port_end: int = 10999,
        max_retries: int = 5,
        backoff_factor: float = 0.5,
        cookie_refresh_threshold: int = 25,
        max_proxy_attempts: int | None = None,
        request_timeout_seconds: float = 10.0,
        cookie_timeout_seconds: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        self.session = session or self._get_session_with_retries(max_retries, backoff_factor)
        self.session.trust_env = False
        self.headers = generate_regrid_headers()
        self.url_cookies = "https://app.regrid.com/"
        self.json_headers = _json_request_headers(self.headers, referer=self.url_cookies)
        self.base_url = "https://app.regrid.com/search.json"
        self.cookie_refresh_threshold = cookie_refresh_threshold
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.request_timeout_seconds = request_timeout_seconds
        self.cookie_timeout_seconds = cookie_timeout_seconds
        self.request_count = 0
        self.lock = threading.Lock()
        self.proxies = self._initialize_proxies(
            smart_proxy=smart_proxy,
            proxy_port_start=proxy_port_start,
            proxy_port_end=proxy_port_end,
        )
        attempt_limit = max_proxy_attempts or len(self.proxies)
        self.max_proxy_attempts = max(1, min(attempt_limit, len(self.proxies)))
        LOGGER.info(
            "Initialized Regrid smart proxy pool with %s endpoints; "
            "max attempts per request=%s; request timeout=%ss; cookie timeout=%ss.",
            len(self.proxies),
            self.max_proxy_attempts,
            self.request_timeout_seconds,
            self.cookie_timeout_seconds,
        )
        self.current_proxy = self._get_next_proxy()
        self.cookies = {"_session_id": self._fetch_new_cookie()}

    def lookup(self, address: str) -> RegridParcelLookupRecord | None:
        start = time.time()
        self._refresh_cookie_if_needed()
        LOGGER.info("Querying Regrid parcel search for address: %s", address)

        try:
            data, search_query_used = self._search(address)
            if not data:
                return None

            first_result = data[0]
            path = first_result.get("path")

            if not path:
                return None
            detail_url = f"https://app.regrid.com{path}.json"
            LOGGER.info("Loading Regrid parcel detail: %s", detail_url)
            detail_response = self._perform_request(
                detail_url,
                headers=self.json_headers,
            )
            detail_response.raise_for_status()
            detail_data = detail_response.json()
            if "fields" not in detail_data or "geometry" not in detail_data:
                return None

            merged = dict(first_result)
            merged["fields"] = detail_data["fields"]
            merged["geometry"] = detail_data["geometry"]
            retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
            return RegridParcelLookupRecord(
                source={
                    "source_id": RegridParcelSourceConnector.source_id,
                    "source_name": "Regrid Parcel Search",
                    "source_url": detail_url,
                    "retrieved_at": retrieved_at,
                    "duration_seconds": round(time.time() - start, 3),
                    "smart_proxy_enabled": True,
                    "search_query_used": search_query_used,
                },
                query={"address": address},
                label=_string_or_none(merged.get("label") or merged.get("address")),
                path=path,
                fields=detail_data["fields"],
                geometry=detail_data["geometry"],
                raw=merged,
            )
        except requests.Timeout as exc:
            raise RegridClientError(
                f"Timeout occurred while querying Regrid for address {address!r}."
            ) from exc
        except requests.ConnectionError as exc:
            raise RegridClientError(
                f"Connection error occurred while querying Regrid for address {address!r}."
            ) from exc
        except requests.RequestException as exc:
            raise RegridClientError(
                f"Error querying Regrid for address {address!r}: {exc}"
            ) from exc

    def _search(self, address: str) -> tuple[list[dict[str, Any]], str]:
        last_error: Exception | None = None
        variants = _search_query_variants(address)
        for index, search_query in enumerate(variants, start=1):
            params = {"query": search_query, "autocomplete": 1, "strict": "false"}
            LOGGER.info(
                "Regrid search variant %s/%s: query=%r",
                index,
                len(variants),
                search_query,
            )
            try:
                response = self._perform_request(
                    self.base_url,
                    params=params,
                    headers=self.json_headers,
                )
                response.raise_for_status()
            except RegridServiceUnavailableError as exc:
                last_error = exc
                LOGGER.warning(
                    "Regrid search variant %s/%s returned service unavailable: %s",
                    index,
                    len(variants),
                    exc,
                )
                continue
            data = response.json()
            if isinstance(data, list) and data:
                LOGGER.info(
                    "Regrid search variant %s returned %s result(s).",
                    index,
                    len(data),
                )
                return data, search_query
            LOGGER.info("Regrid search variant %s returned no results.", index)

        if last_error:
            raise RegridClientError(
                "All Regrid search query variants failed. Last error: "
                f"{last_error}"
            ) from last_error
        LOGGER.debug("No Regrid results found for address %r.", address)
        return [], variants[0]

    def _get_session_with_retries(
        self,
        max_retries: int,
        backoff_factor: float,
    ) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        LOGGER.info(
            "Using explicit Regrid retry loop; urllib3 internal retries are disabled "
            "and requests environment proxy discovery is disabled "
            "(configured max_retries=%s, backoff_factor=%s).",
            max_retries,
            backoff_factor,
        )
        adapter = HTTPAdapter(max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _initialize_proxies(
        self,
        *,
        smart_proxy: str,
        proxy_port_start: int,
        proxy_port_end: int,
    ) -> list[dict[str, str]]:
        proxy_host = _proxy_host(smart_proxy)
        if not proxy_host:
            raise RegridProxyConfigurationError("TITLE_MCP_SMART_PROXY is required.")
        return [
            {
                "http": f"http://{proxy_host}:{port}",
                "https": f"https://{proxy_host}:{port}",
            }
            for port in range(proxy_port_start, proxy_port_end + 1)
        ]

    def _get_next_proxy(self) -> dict[str, str]:
        if not self.proxies:
            raise RegridProxyConfigurationError("No Regrid smart proxies are configured.")
        proxy = random.choice(self.proxies)
        LOGGER.debug("Using Regrid smart proxy endpoint: %s", proxy)
        return proxy

    def _fetch_new_cookie(self) -> str:
        last_error: Exception | None = None
        LOGGER.info(
            "Fetching Regrid session cookie through smart proxy pool (%s attempts max).",
            self.max_proxy_attempts,
        )
        for attempt in range(1, self.max_proxy_attempts + 1):
            proxy = self._get_next_proxy()
            self.current_proxy = proxy
            start = time.monotonic()
            LOGGER.info(
                "Regrid cookie HEAD attempt %s/%s: url=%s proxy=%s timeout=%ss.",
                attempt,
                self.max_proxy_attempts,
                self.url_cookies,
                _redacted_proxy_map(proxy),
                self.cookie_timeout_seconds,
            )
            try:
                response = self.session.head(
                    self.url_cookies,
                    headers=self.headers,
                    proxies=proxy,
                    timeout=self.cookie_timeout_seconds,
                )
                elapsed = time.monotonic() - start
                LOGGER.info(
                    "Regrid cookie HEAD attempt %s returned HTTP %s in %.3fs.",
                    attempt,
                    response.status_code,
                    elapsed,
                )
                response.raise_for_status()
                set_cookie_header = response.headers.get("Set-Cookie", "")
                session_cookie = _session_cookie_from_header(set_cookie_header)
                if not session_cookie:
                    raise RegridClientError("Failed to retrieve Regrid session cookie.")
                LOGGER.info("Fetched new Regrid session cookie on attempt %s.", attempt)
                return session_cookie
            except (requests.RequestException, RegridClientError) as exc:
                last_error = exc
                elapsed = time.monotonic() - start
                LOGGER.warning(
                    "Regrid session cookie attempt %s/%s failed after %.3fs: %s",
                    attempt,
                    self.max_proxy_attempts,
                    elapsed,
                    exc,
                )

        raise RegridClientError(
            "Error fetching Regrid session cookie after "
            f"{self.max_proxy_attempts} proxy attempt(s): {last_error}"
        ) from last_error

    def _refresh_cookie_if_needed(self) -> None:
        with self.lock:
            if self.request_count >= self.cookie_refresh_threshold:
                LOGGER.debug("Refreshing Regrid session cookie due to usage threshold.")
                self.cookies["_session_id"] = self._fetch_new_cookie()
                self.request_count = 0
            self.request_count += 1

    def _perform_request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        attempts = 0
        rate_limit_attempts = 0
        max_attempts = self.max_proxy_attempts
        last_error: Exception | None = None
        while attempts < max_attempts and rate_limit_attempts < 2:
            attempt_number = attempts + 1
            start = time.monotonic()
            try:
                LOGGER.info(
                    "Regrid GET attempt %s/%s: url=%s params=%s proxy=%s timeout=%ss.",
                    attempt_number,
                    max_attempts,
                    url,
                    params or {},
                    _redacted_proxy_map(self.current_proxy),
                    self.request_timeout_seconds,
                )
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers or self.headers,
                    proxies=self.current_proxy,
                    cookies=self.cookies,
                    timeout=self.request_timeout_seconds,
                )
                elapsed = time.monotonic() - start
                LOGGER.info(
                    "Regrid GET attempt %s returned HTTP %s in %.3fs.",
                    attempt_number,
                    response.status_code,
                    elapsed,
                )
                if response.status_code == 429:
                    last_error = RegridClientError("Regrid returned HTTP 429.")
                    LOGGER.warning(
                        "Regrid returned 429. Retrying with a new cookie and proxy."
                    )
                    self.cookies["_session_id"] = self._fetch_new_cookie()
                    self.current_proxy = self._get_next_proxy()
                    rate_limit_attempts += 1
                    attempts += 1
                    continue
                if (
                    response.status_code == 503
                    and _is_regrid_service_unavailable_response(response)
                ):
                    body_preview = _response_text_preview(response)
                    raise RegridServiceUnavailableError(
                        "Regrid returned HTTP 503 Service Unavailable. "
                        f"Body preview={body_preview!r}"
                    )
                if response.status_code in {500, 502, 503, 504}:
                    attempts += 1
                    body_preview = _response_text_preview(response)
                    last_error = RegridClientError(
                        f"Regrid returned HTTP {response.status_code}. "
                        f"Body preview={body_preview!r}"
                    )
                    LOGGER.warning(
                        "Regrid returned HTTP %s on attempt %s/%s. Body preview=%r. "
                        "Switching proxy.",
                        response.status_code,
                        attempt_number,
                        max_attempts,
                        body_preview,
                    )
                    self.current_proxy = self._get_next_proxy()
                    continue
                LOGGER.info("Regrid request returned HTTP %s.", response.status_code)
                return response
            except ProxyError as exc:
                attempts += 1
                last_error = exc
                elapsed = time.monotonic() - start
                LOGGER.warning(
                    "Regrid smart proxy failed on attempt %s/%s after %.3fs: %s. "
                    "Switching proxy.",
                    attempt_number,
                    max_attempts,
                    elapsed,
                    exc,
                )
                self.current_proxy = self._get_next_proxy()
            except requests.Timeout as exc:
                attempts += 1
                last_error = exc
                elapsed = time.monotonic() - start
                LOGGER.warning(
                    "Regrid GET attempt %s/%s timed out after %.3fs: %s. "
                    "Switching proxy.",
                    attempt_number,
                    max_attempts,
                    elapsed,
                    exc,
                )
                self.current_proxy = self._get_next_proxy()
            except requests.RequestException:
                raise
        raise RegridClientError(
            "All Regrid smart proxy attempts failed."
            f" Last error: {last_error}"
        )


def canonical_parcel_record_from_regrid(record: RegridParcelLookupRecord) -> ParcelRecord:
    fields = record.fields
    raw_hit = {key: value for key, value in record.raw.items() if key not in {"fields", "geometry"}}
    state = _string_or_none(fields.get("state2"))
    county = _normalize_county(fields.get("county"))
    municipality = _title_or_none(fields.get("scity") or fields.get("city"))
    parcel_number = _string_or_none(fields.get("parcelnumb") or record.raw.get("parcelnumb"))
    normalized_parcel_number = _string_or_none(fields.get("parcelnumb_no_formatting"))
    owners = _owner_names(fields)
    search_query_used = _string_or_none(record.source.get("search_query_used"))

    return ParcelRecord(
        source=ParcelRecordSource(
            source_id=str(record.source.get("source_id") or RegridParcelSourceConnector.source_id),
            source_name=_string_or_none(record.source.get("source_name")),
            source_url=_string_or_none(record.source.get("source_url")),
            retrieved_at=_string_or_none(record.source.get("retrieved_at")),
            duration_seconds=_float_or_none(record.source.get("duration_seconds")),
        ),
        jurisdiction=Jurisdiction(
            country="US",
            state=state,
            county=county,
            municipality=municipality,
        ),
        search=ParcelSearchContext(
            query=dict(record.query),
            normalized_query=search_query_used,
            result_count=1,
            result_index=0,
            result_hit=raw_hit,
        ),
        identifiers=ParcelIdentifiers(
            parcel_id=_string_or_none(fields.get("parcelid") or parcel_number),
            parcel_number=parcel_number,
            normalized_parcel_number=normalized_parcel_number,
            account_number=_string_or_none(fields.get("account_number")),
            tax_id=_string_or_none(fields.get("tax_id")),
            stable_id_field=_string_or_none(fields.get("ll_stable_id")),
            uuid=_string_or_none(fields.get("ll_uuid")),
            stack_uuid=_string_or_none(fields.get("ll_stack_uuid")),
            path=record.path or _string_or_none(fields.get("path")),
            alternate_ids=_alternate_ids(fields),
        ),
        ownership=ParcelOwnership(
            owner_display=owners[0] if owners else None,
            owners=owners,
            mailing_address=_mailing_address(fields),
            mailing_address_lines=_mailing_address_lines(fields),
            raw={
                key: fields.get(key)
                for key in [
                    "owner",
                    "unmodified_owner",
                    "ownfrst",
                    "ownlast",
                    "owner2",
                    "owner3",
                    "owner4",
                    "ownernme2",
                    "previous_owner",
                    "owntype",
                    "mailadd",
                    "mail_city",
                    "mail_state2",
                    "mail_zip",
                    "formatted_mailing_address",
                ]
                if _present(fields.get(key))
            },
        ),
        site=ParcelSite(
            address_display=_string_or_none(fields.get("address") or record.raw.get("headline")),
            address=_site_address(fields),
            legal_description=_string_or_none(fields.get("legaldesc")),
            acreage_deeded=_decimal_or_none(fields.get("deeded_acres")),
            acreage_gis=_decimal_or_none(fields.get("gisacre")),
            acreage_regrid=_decimal_or_none(fields.get("ll_gisacre")),
            square_feet_gis=_decimal_or_none(fields.get("ll_gissqft") or fields.get("sqft")),
            raw={
                key: fields.get(key)
                for key in [
                    "address",
                    "address2",
                    "saddno",
                    "saddpref",
                    "saddstr",
                    "saddsttyp",
                    "saddstsuf",
                    "sunit",
                    "scity",
                    "state2",
                    "szip",
                    "original_address",
                    "legaldesc",
                    "deeded_acres",
                    "gisacre",
                    "ll_gisacre",
                    "ll_gissqft",
                ]
                if _present(fields.get(key))
            },
        ),
        land_use=ParcelLandUse(
            property_class=_string_or_none(fields.get("pclass")),
            use_code=_string_or_none(fields.get("usecode")),
            use_description=_string_or_none(fields.get("usedesc")),
            zoning_code=_string_or_none(fields.get("zoning")),
            zoning_description=_string_or_none(fields.get("zoning_description")),
            zoning_type=_string_or_none(fields.get("zoning_type")),
            zoning_subtype=_string_or_none(fields.get("zoning_subtype")),
            zoning_code_link=_string_or_none(fields.get("zoning_code_link")),
            owner_occupied=_bool_or_none(fields.get("owneroccupied")),
            homestead_exemption=_bool_or_none(fields.get("homestead_exemption")),
            rental=_bool_or_none(fields.get("rental")),
            cauv=_bool_or_none(fields.get("cauv")),
            qualified_opportunity_zone=_bool_or_none(fields.get("qoz")),
            raw={
                key: fields.get(key)
                for key in [
                    "usecode",
                    "usedesc",
                    "zoning",
                    "zoning_description",
                    "zoning_type",
                    "zoning_subtype",
                    "pclass",
                    "owneroccupied",
                    "homestead_exemption",
                    "rental",
                    "cauv",
                    "qoz",
                ]
                if _present(fields.get(key))
            },
        ),
        valuation=ParcelValuation(
            value_type=_string_or_none(fields.get("parvaltype")),
            land_value=_money_or_none(fields.get("landval")),
            improvement_value=_money_or_none(fields.get("improvval")),
            total_value=_money_or_none(fields.get("parval")),
            agricultural_value=_money_or_none(fields.get("agval")),
            sale_price=_money_or_none(fields.get("saleprice")),
            sale_date=_string_or_none(fields.get("saledate")),
            last_transfer_date=_string_or_none(fields.get("last_ownership_transfer_date")),
            tax_amount=_money_or_none(fields.get("taxamt")),
            tax_year=_string_or_none(fields.get("taxyear")),
            raw={
                key: fields.get(key)
                for key in [
                    "parvaltype",
                    "landval",
                    "improvval",
                    "parval",
                    "agval",
                    "saleprice",
                    "saledate",
                    "last_ownership_transfer_date",
                    "taxamt",
                    "taxyear",
                ]
                if _present(fields.get(key))
            },
        ),
        building=_building(fields),
        geography=ParcelGeography(
            latitude=_decimal_or_none(fields.get("lat")),
            longitude=_decimal_or_none(fields.get("lon")),
            centroid=record.raw.get("centroid"),
            geometry=record.geometry,
            geoid=_string_or_none(fields.get("geoid")),
            census_tract=_string_or_none(fields.get("census_tract")),
            census_block=_string_or_none(fields.get("census_block")),
            census_block_group=_string_or_none(fields.get("census_blockgroup")),
            census_zcta=_string_or_none(fields.get("census_zcta")),
            school_district=_string_or_none(
                fields.get("census_unified_school_district") or fields.get("schldscrp")
            ),
            plss_township=_string_or_none(fields.get("plss_township")),
            plss_section=_string_or_none(fields.get("plss_section")),
            plss_range=_string_or_none(fields.get("plss_range")),
            raw={
                key: fields.get(key)
                for key in [
                    "geoid",
                    "lat",
                    "lon",
                    "census_tract",
                    "census_block",
                    "census_blockgroup",
                    "census_zcta",
                    "census_unified_school_district",
                    "plss_township",
                    "plss_section",
                    "plss_range",
                ]
                if _present(fields.get(key))
            },
        ),
        source_specific={
            "regrid": {
                "schema_name": record.schema_name,
                "schema_version": record.schema_version,
                "record_type": record.record_type,
                "path": record.path,
                "label": record.label,
                "fields": fields,
                "geometry": record.geometry,
                "search_result": raw_hit,
                "query": record.query,
                "source": record.source,
            }
        },
    )


class RegridParcelSourceConnector(SourceConnector):
    source_id = "regrid-parcel-search"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Regrid Parcel Search",
        kind=SourceKind.VENDOR_API,
        jurisdiction_scope=JurisdictionScope(country="US"),
        priority=120,
        owner="Regrid",
        base_url="https://app.regrid.com/",
        requires_auth=True,
        metadata={
            "requires_smart_proxy": True,
            "required_env_vars": ["TITLE_MCP_SMART_PROXY"],
            "legacy_env_vars": ["SMART_PROXY"],
        },
    )

    def __init__(
        self,
        *,
        settings: TitleMCPSettings | None = None,
        service: _RegridParcelServiceProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._service = service

    def supports(self, jurisdiction: Jurisdiction, kind: SourceKind | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        service = self._service
        if service is None:
            try:
                service = self._service_from_settings()
            except RegridProxyConfigurationError as exc:
                return SourceResult(
                    source_id=self.source_id,
                    status=SourceResultStatus.REQUIRES_CONFIGURATION,
                    warnings=[str(exc)],
                    metadata={
                        "required_env_vars": ["TITLE_MCP_SMART_PROXY"],
                        "legacy_env_vars": ["SMART_PROXY"],
                    },
                )
            except Exception as exc:
                return SourceResult(
                    source_id=self.source_id,
                    status=SourceResultStatus.FAILED,
                    warnings=[f"Failed to initialize Regrid parcel lookup: {exc}"],
                )

        try:
            lookup_query = RegridParcelLookupQuery.model_validate(query.criteria)
            record = await asyncio.to_thread(service.lookup, lookup_query.address)
        except Exception as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"Regrid parcel lookup failed: {exc}"],
            )

        if record is None:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.NO_RESULTS,
                warnings=[],
                metadata={"address": query.criteria.get("address")},
            )

        canonical_record = canonical_parcel_record_from_regrid(record)
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=[canonical_record.model_dump(mode="json")],
            citations=[
                SourceCitation(
                    label="Regrid Parcel Search",
                    uri=canonical_record.source.source_url or self.descriptor.base_url,
                    retrieved_at=canonical_record.source.retrieved_at,
                )
            ],
            warnings=[],
            requires_human_review=True,
            metadata={
                "canonical_schema": canonical_record.schema_name,
                "canonical_schema_version": canonical_record.schema_version,
                "record_count": 1,
                "smart_proxy_enabled": True,
            },
        )

    def _service_from_settings(self) -> RegridParcelQueryService:
        smart_proxy = self.settings.smart_proxy
        if not smart_proxy:
            import os

            smart_proxy = os.environ.get("SMART_PROXY")
        if not smart_proxy:
            raise RegridProxyConfigurationError(
                "Set TITLE_MCP_SMART_PROXY in .env before querying Regrid. "
                "The legacy SMART_PROXY variable is also supported."
            )
        self._service = RegridParcelQueryService(
            smart_proxy=smart_proxy,
            proxy_port_start=self.settings.regrid_proxy_port_start,
            proxy_port_end=self.settings.regrid_proxy_port_end,
            max_retries=self.settings.regrid_max_retries,
            backoff_factor=self.settings.regrid_backoff_factor,
            cookie_refresh_threshold=self.settings.regrid_cookie_refresh_threshold,
            max_proxy_attempts=self.settings.regrid_max_proxy_attempts,
            request_timeout_seconds=self.settings.regrid_timeout_seconds,
            cookie_timeout_seconds=self.settings.regrid_cookie_timeout_seconds,
        )
        return self._service


def _proxy_host(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    cleaned = re.sub(r"^https?://", "", cleaned)
    return cleaned


def _session_cookie_from_header(value: str) -> str | None:
    if not value:
        return None
    match = re.search(r"_session_id=([^;]+)", value)
    if match:
        return match.group(1)
    first = value.split(";", 1)[0]
    if "=" not in first:
        return None
    return first.split("=", 1)[1] or None


def _json_request_headers(headers: dict[str, str], *, referer: str) -> dict[str, str]:
    json_headers = dict(headers)
    json_headers.update(
        {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "referer": referer,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-requested-with": "XMLHttpRequest",
        }
    )
    json_headers.pop("upgrade-insecure-requests", None)
    return json_headers


def _search_query_variants(address: str) -> list[str]:
    original = _collapse_spaces(address)
    comma_free = _collapse_spaces(original.replace(",", " "))
    street_only = _collapse_spaces(original.split(",", 1)[0]) if "," in original else ""
    variants: list[str] = []
    for value in [comma_free, street_only, original]:
        if value and value not in variants:
            variants.append(value)
    return variants or [original]


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_regrid_service_unavailable_response(response: requests.Response) -> bool:
    if response.status_code != 503:
        return False
    text = response.text or ""
    return "Service Unavailable" in text or '"code": "503"' in text or '"code":"503"' in text


def _redacted_proxy_map(proxy: dict[str, str] | None) -> dict[str, str] | None:
    if proxy is None:
        return None
    return {
        scheme: _redacted_proxy_url(url)
        for scheme, url in proxy.items()
        if scheme in {"http", "https"}
    }


def _redacted_proxy_url(value: str) -> str:
    text = str(value)
    text = re.sub(r"//([^:@/\s]+):([^@/\s]+)@", "//***:***@", text)
    return re.sub(r"^([^:@/\s]+):([^@/\s]+)@", "***:***@", text)


def _response_text_preview(response: requests.Response, limit: int = 240) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    return " ".join(text.split())[:limit]


def _normalize_county(value: Any) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    return re.sub(r"\s+County$", "", text, flags=re.IGNORECASE)


def _title_or_none(value: Any) -> str | None:
    text = _string_or_none(value)
    return text.replace("-", " ").title() if text else None


def _site_address(fields: dict[str, Any]) -> Address | None:
    line1 = _string_or_none(fields.get("address"))
    if not line1:
        return None
    return Address(
        line1=line1,
        line2=_string_or_none(fields.get("address2") or fields.get("sunit")),
        city=_title_or_none(fields.get("scity") or fields.get("city")),
        state=_string_or_none(fields.get("state2")),
        postal_code=_string_or_none(fields.get("szip") or fields.get("szip5")),
    )


def _mailing_address(fields: dict[str, Any]) -> Address | None:
    line1 = _string_or_none(fields.get("mailadd"))
    if not line1:
        return None
    return Address(
        line1=line1,
        line2=_string_or_none(fields.get("mail_address2") or fields.get("mail_unit")),
        city=_title_or_none(fields.get("mail_city")),
        state=_string_or_none(fields.get("mail_state2")),
        postal_code=_string_or_none(fields.get("mail_zip")),
    )


def _mailing_address_lines(fields: dict[str, Any]) -> list[str]:
    formatted = fields.get("formatted_mailing_address")
    if isinstance(formatted, list):
        return [_collapse_spaces(str(line)) for line in formatted if _string_or_none(line)]
    lines = []
    if fields.get("mailadd"):
        lines.append(_collapse_spaces(str(fields["mailadd"])))
    city_line = " ".join(
        part
        for part in [
            _string_or_none(fields.get("mail_city")),
            _string_or_none(fields.get("mail_state2")),
            _string_or_none(fields.get("mail_zip")),
        ]
        if part
    )
    if city_line:
        lines.append(city_line)
    return lines


def _owner_names(fields: dict[str, Any]) -> list[str]:
    combined_person = " ".join(
        part
        for part in [
            _string_or_none(fields.get("ownfrst")),
            _string_or_none(fields.get("ownlast")),
        ]
        if part
    )
    values = [
        fields.get("owner"),
        fields.get("unmodified_owner"),
        combined_person,
        fields.get("owner2"),
        fields.get("owner3"),
        fields.get("owner4"),
        fields.get("ownernme2"),
    ]
    owners: list[str] = []
    for value in values:
        owner = _string_or_none(value)
        if owner and owner not in owners:
            owners.append(owner)
    return owners


def _alternate_ids(fields: dict[str, Any]) -> dict[str, str]:
    keys = [
        "state_parcelnumb",
        "account_number",
        "tax_id",
        "alt_parcelnumb1",
        "alt_parcelnumb2",
        "alt_parcelnumb3",
        "guid",
        "cvttxcd",
        "schltxcd",
    ]
    return {key: str(fields[key]) for key in keys if _string_or_none(fields.get(key))}


def _building(fields: dict[str, Any]) -> ParcelBuilding | None:
    values = {
        "year_built": _int_or_none(fields.get("yearbuilt")),
        "effective_year_built": _string_or_none(fields.get("year_built_effective_date")),
        "stories": _decimal_or_none(fields.get("numstories")),
        "units": _int_or_none(fields.get("numunits")),
        "rooms": _decimal_or_none(fields.get("numrooms")),
        "bedrooms": _int_or_none(fields.get("num_bedrooms") or fields.get("bedrms")),
        "full_baths": _decimal_or_none(fields.get("num_bath")),
        "half_baths": _decimal_or_none(fields.get("num_bath_partial") or fields.get("hbaths")),
        "total_baths": _decimal_or_none(fields.get("num_baths") or fields.get("num_bath")),
        "building_area_sqft": _decimal_or_none(
            fields.get("area_building") or fields.get("resflrarea_ag")
        ),
        "building_area_definition": _string_or_none(fields.get("area_building_definition")),
        "style": _string_or_none(fields.get("structstyle")),
    }
    if not any(value is not None for value in values.values()):
        return None
    return ParcelBuilding(
        **values,
        raw={
            key: fields.get(key)
            for key in [
                "yearbuilt",
                "year_built_effective_date",
                "numstories",
                "numunits",
                "numrooms",
                "num_bedrooms",
                "bedrms",
                "num_bath",
                "num_bath_partial",
                "hbaths",
                "num_baths",
                "area_building",
                "resflrarea_ag",
                "area_building_definition",
                "structstyle",
            ]
            if _present(fields.get(key))
        },
    )


def _money_or_none(value: Any) -> MoneyAmount | None:
    amount = _decimal_or_none(value)
    if amount is None:
        return None
    return MoneyAmount(value=amount, display=f"{amount:,.2f}")


def _decimal_or_none(value: Any) -> Decimal | None:
    if not _present(value):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _int_or_none(value: Any) -> int | None:
    number = _decimal_or_none(value)
    return int(number) if number is not None else None


def _float_or_none(value: Any) -> float | None:
    if not _present(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    text = _string_or_none(value)
    if text is None:
        return None
    normalized = text.lower()
    if normalized in {"y", "yes", "true", "1"}:
        return True
    if normalized in {"n", "no", "false", "0"}:
        return False
    return None


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

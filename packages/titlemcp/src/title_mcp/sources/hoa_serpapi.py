from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
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

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-])?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}\b"
)
_SENSITIVE_QUERY_KEYS = {"api_key"}
_CONTACT_PATH_TERMS = (
    "contact",
    "email",
    "management",
    "assessment",
    "payment",
    "board",
    "trustee",
)
_THIRD_PARTY_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "zoominfo.com",
    "bizapedia.com",
    "opencorporates.com",
    "corporationwiki.com",
    "dnb.com",
    "buzzfile.com",
)

_PAGE_BODY_BYTE_LIMIT = 1_500_000
_PAGE_TEXT_CHAR_LIMIT = 20_000
_PAGE_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; TitleMCP-HOA/1.0; +https://github.com/anthropics)"
)
_PAGE_FETCH_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "head", "svg"}
)

_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}


class SerpApiClientError(RuntimeError):
    pass


class HoaContactSearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    hoa_name: str = Field(min_length=1)
    state: str | None = None
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value or None


class HoaContactCandidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rank: int
    source_type: str
    name: str | None = None
    website: str | None = None
    source_url: str | None = None
    address: str | None = None
    phone_numbers: list[str] = Field(default_factory=list)
    email_addresses: list[str] = Field(default_factory=list)
    snippet: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class HoaPageFetch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    url: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    title: str | None = None
    text: str | None = None
    text_length: int = 0
    truncated: bool = False
    error: str | None = None
    duration_seconds: float = 0.0


class HoaContactSearchRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.hoa_contact_search"
    schema_version: str = "1.1"
    record_type: str = "hoa_contact_search"
    source: dict[str, Any]
    query: dict[str, Any]
    search_parameters: dict[str, Any]
    hoa_name: str
    state: str | None = None
    result_count: int
    best_match: HoaContactCandidate | None = None
    candidates: list[HoaContactCandidate] = Field(default_factory=list)
    email_addresses: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    first_result_page: HoaPageFetch | None = None
    duration_seconds: float
    source_specific: dict[str, Any] = Field(default_factory=dict)


class _SerpApiHoaContactClientProtocol(Protocol):
    def hoa_contact_search(self, query: HoaContactSearchQuery) -> HoaContactSearchRecord:
        """Search for HOA contact information through SerpAPI."""


class SerpApiHoaContactClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        page_fetcher: Callable[[str], HoaPageFetch] | None = None,
        page_fetch_timeout: float | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.endpoint = "https://serpapi.com/search.json"
        self.page_fetch_timeout = page_fetch_timeout or timeout
        self._page_fetcher = page_fetcher

    def hoa_contact_search(self, query: HoaContactSearchQuery) -> HoaContactSearchRecord:
        start = time.time()
        query = HoaContactSearchQuery.model_validate(query)
        LOGGER.info(
            "Searching SerpAPI for HOA contact information: hoa_name=%r state=%r.",
            query.hoa_name,
            query.state,
        )

        domain_params = build_hoa_domain_search_params(query)
        domain_data = self._search(domain_params)
        domain_candidates = _extract_candidates(domain_data, max_results=query.max_results)
        official_domain = _select_official_domain(domain_candidates, hoa_name=query.hoa_name)
        searches = [
            {
                "stage": "domain_lookup",
                "search_parameters": domain_params,
                "data": domain_data,
            }
        ]

        if official_domain:
            LOGGER.info(
                "SerpAPI HOA search selected official domain candidate: %s",
                official_domain,
            )
            contact_params = build_hoa_site_contact_search_params(query, official_domain)
            searches.append(
                {
                    "stage": "site_contact_lookup",
                    "search_parameters": contact_params,
                    "data": self._search(contact_params),
                }
            )
        else:
            LOGGER.info(
                "SerpAPI HOA search did not identify an official domain; "
                "falling back to broad contact search."
            )
            contact_params = build_hoa_contact_search_params(query)
            searches.append(
                {
                    "stage": "contact_lookup",
                    "search_parameters": contact_params,
                    "data": self._search(contact_params),
                }
            )

        record = hoa_contact_record_from_serpapi_searches(
            query=query,
            searches=searches,
            official_domain=official_domain,
            duration_seconds=round(time.time() - start, 3),
        )

        target_url = _first_result_url(record)
        if target_url:
            LOGGER.info(
                "Fetching top SerpAPI result for LLM contact extraction: %s",
                target_url,
            )
            fetcher = self._page_fetcher or (
                lambda url: _fetch_page_text(url, timeout=self.page_fetch_timeout)
            )
            record = record.model_copy(update={"first_result_page": fetcher(target_url)})

        return record

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "api_key": self.api_key}
        try:
            response = self.session.get(
                self.endpoint,
                params=request_params,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SerpApiClientError(f"SerpAPI request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise SerpApiClientError("SerpAPI returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise SerpApiClientError("SerpAPI returned an unexpected response shape.")
        if data.get("error"):
            raise SerpApiClientError(str(data["error"]))
        return data


class HoaContactSerpApiSourceConnector(SourceConnector):
    source_id = "serpapi-hoa-contact-search"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="SerpAPI HOA Contact Search",
        kind=SourceKind.HOA,
        jurisdiction_scope=JurisdictionScope(country="US"),
        priority=110,
        owner="SerpAPI",
        base_url="https://serpapi.com/search-api",
        requires_auth=True,
        metadata={
            "api": "SerpAPI Google Search API",
            "required_env_vars": ["TITLE_MCP_SERPAPI_API_KEY"],
            "returns_schema": "title_mcp.hoa_contact_search",
        },
    )

    def __init__(
        self,
        *,
        settings: TitleMCPSettings | None = None,
        client: _SerpApiHoaContactClientProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def supports(self, jurisdiction: Jurisdiction, kind: SourceKind | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        client = self._client or self._client_from_settings()
        if client is None:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    "Set TITLE_MCP_SERPAPI_API_KEY in .env before querying HOA contacts."
                ],
                metadata={"required_env_vars": ["TITLE_MCP_SERPAPI_API_KEY"]},
            )

        try:
            search_query = HoaContactSearchQuery.model_validate(query.criteria)
            record = await asyncio.to_thread(client.hoa_contact_search, search_query)
        except Exception as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"HOA contact search failed: {exc}"],
            )

        status = (
            SourceResultStatus.SUCCEEDED
            if record.result_count
            else SourceResultStatus.NO_RESULTS
        )
        metadata: dict[str, Any] = {
            "canonical_schema": record.schema_name,
            "canonical_schema_version": record.schema_version,
            "result_count": record.result_count,
            "email_count": len(record.email_addresses),
            "phone_count": len(record.phone_numbers),
        }
        if record.first_result_page is not None:
            page = record.first_result_page
            metadata["first_result_page"] = {
                "url": page.url,
                "final_url": page.final_url,
                "status_code": page.status_code,
                "text_length": page.text_length,
                "truncated": page.truncated,
                "fetch_error": page.error,
            }
        warnings: list[str] = []
        if record.first_result_page and record.first_result_page.error:
            warnings.append(
                f"Failed to fetch first result page {record.first_result_page.url}: "
                f"{record.first_result_page.error}"
            )
        return SourceResult(
            source_id=self.source_id,
            status=status,
            records=[record.model_dump(mode="json")],
            citations=_citations_for_record(record),
            warnings=warnings,
            requires_human_review=True,
            metadata=metadata,
        )

    def _client_from_settings(self) -> SerpApiHoaContactClient | None:
        if not self.settings.serpapi_api_key:
            return None
        self._client = SerpApiHoaContactClient(
            self.settings.serpapi_api_key,
            timeout=self.settings.serpapi_timeout_seconds,
        )
        return self._client


def build_hoa_contact_search_params(query: HoaContactSearchQuery) -> dict[str, Any]:
    terms = [
        f'"{query.hoa_name}"',
        '("contact" OR "management company" OR assessment OR payments OR board)',
        "(email OR phone OR address)",
    ]
    if query.state:
        terms.append(query.state)
    terms.extend(
        [
            "-site:facebook.com",
            "-site:instagram.com",
            "-site:linkedin.com",
            "-site:zoominfo.com",
        ]
    )
    params: dict[str, Any] = {
        "engine": "google",
        "q": " ".join(terms),
        "google_domain": "google.com",
        "hl": "en",
        "gl": "us",
    }
    location = _state_location(query.state)
    if location:
        params["location"] = location
    return params


def build_hoa_domain_search_params(query: HoaContactSearchQuery) -> dict[str, Any]:
    terms = [
        f'"{query.hoa_name}"',
        "(HOA OR homeowners association)",
    ]
    if query.state:
        terms.append(query.state)
    terms.extend(
        [
            "-site:facebook.com",
            "-site:instagram.com",
            "-site:linkedin.com",
            "-site:zoominfo.com",
        ]
    )
    params: dict[str, Any] = {
        "engine": "google",
        "q": " ".join(terms),
        "google_domain": "google.com",
        "hl": "en",
        "gl": "us",
    }
    location = _state_location(query.state)
    if location:
        params["location"] = location
    return params


def build_hoa_site_contact_search_params(
    query: HoaContactSearchQuery,
    domain: str,
) -> dict[str, Any]:
    terms = [
        f"site:{domain}",
        '("contact" OR "management company" OR assessment OR payments OR board OR email)',
        "(email OR phone OR address)",
    ]
    params: dict[str, Any] = {
        "engine": "google",
        "q": " ".join(terms),
        "google_domain": "google.com",
        "hl": "en",
        "gl": "us",
    }
    location = _state_location(query.state)
    if location:
        params["location"] = location
    return params


def hoa_contact_record_from_serpapi(
    *,
    query: HoaContactSearchQuery,
    search_parameters: dict[str, Any],
    data: dict[str, Any],
    duration_seconds: float,
) -> HoaContactSearchRecord:
    return hoa_contact_record_from_serpapi_searches(
        query=query,
        searches=[
            {
                "stage": "contact_lookup",
                "search_parameters": search_parameters,
                "data": data,
            }
        ],
        official_domain=None,
        duration_seconds=duration_seconds,
    )


def hoa_contact_record_from_serpapi_searches(
    *,
    query: HoaContactSearchQuery,
    searches: list[dict[str, Any]],
    official_domain: str | None,
    duration_seconds: float,
) -> HoaContactSearchRecord:
    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    candidates = _candidates_from_searches(searches, max_results=query.max_results)
    best_match = _best_candidate(candidates, hoa_name=query.hoa_name)
    email_addresses = _unique(
        email for candidate in candidates for email in candidate.email_addresses
    )
    phone_numbers = _unique(
        phone for candidate in candidates for phone in candidate.phone_numbers
    )
    addresses = _unique(
        candidate.address for candidate in candidates if candidate.address
    )
    websites = _unique(
        candidate.website for candidate in candidates if candidate.website
    )
    search_summaries = _serpapi_search_summaries(searches)
    primary_parameters = (
        search_summaries[-1]["search_parameters"] if search_summaries else {}
    )
    return HoaContactSearchRecord(
        source={
            "source_id": HoaContactSerpApiSourceConnector.source_id,
            "source_name": "SerpAPI HOA Contact Search",
            "source_url": "https://serpapi.com/search-api",
            "retrieved_at": retrieved_at,
            "duration_seconds": duration_seconds,
        },
        query=query.model_dump(mode="json"),
        search_parameters=primary_parameters,
        hoa_name=query.hoa_name,
        state=query.state,
        result_count=len(candidates),
        best_match=best_match,
        candidates=candidates,
        email_addresses=email_addresses,
        phone_numbers=phone_numbers,
        addresses=addresses,
        websites=websites,
        duration_seconds=duration_seconds,
        source_specific={
            "serpapi": {
                "official_domain": official_domain,
                "searches": search_summaries,
            }
        },
    )


def _extract_candidates(
    data: dict[str, Any],
    *,
    max_results: int,
    organic_source_type: str = "organic_result",
) -> list[HoaContactCandidate]:
    candidates: list[HoaContactCandidate] = []
    knowledge_graph = data.get("knowledge_graph")
    if isinstance(knowledge_graph, dict):
        candidates.append(
            _candidate_from_mapping(
                source_type="knowledge_graph",
                fallback_rank=1,
                mapping=knowledge_graph,
            )
        )

    for index, result in enumerate(_local_result_items(data.get("local_results")), start=1):
        candidates.append(
            _candidate_from_mapping(
                source_type="local_result",
                fallback_rank=index,
                mapping=result,
            )
        )

    organic_results = data.get("organic_results") or []
    if isinstance(organic_results, list):
        for index, result in enumerate(organic_results[:max_results], start=1):
            if isinstance(result, dict):
                candidates.append(
                    _candidate_from_mapping(
                        source_type=organic_source_type,
                        fallback_rank=index,
                        mapping=result,
                    )
                )

    return [_deduplicate_candidate_fields(candidate) for candidate in candidates[:max_results]]


def _candidates_from_searches(
    searches: list[dict[str, Any]],
    *,
    max_results: int,
) -> list[HoaContactCandidate]:
    grouped: dict[str, list[HoaContactCandidate]] = {
        "site_contact_lookup": [],
        "contact_lookup": [],
        "domain_lookup": [],
    }
    for search in searches:
        stage = str(search.get("stage") or "contact_lookup")
        data = search.get("data") if isinstance(search.get("data"), dict) else {}
        grouped.setdefault(stage, []).extend(
            _extract_candidates(
                data,
                max_results=max_results,
                organic_source_type=(
                    "site_result" if stage == "site_contact_lookup" else "organic_result"
                ),
            )
        )

    ordered: list[HoaContactCandidate] = []
    for stage in ("site_contact_lookup", "contact_lookup", "domain_lookup"):
        ordered.extend(grouped.get(stage) or [])
    return _deduplicate_candidates(ordered)[:max_results]


def _deduplicate_candidates(
    candidates: list[HoaContactCandidate],
) -> list[HoaContactCandidate]:
    seen: set[str] = set()
    deduped: list[HoaContactCandidate] = []
    by_key: dict[str, int] = {}
    for candidate in candidates:
        key = (candidate.source_url or candidate.website or candidate.name or "").casefold()
        if not key:
            key = f"{candidate.source_type}:{candidate.rank}"
        if key in seen:
            deduped[by_key[key]] = _merge_candidates(deduped[by_key[key]], candidate)
            continue
        seen.add(key)
        by_key[key] = len(deduped)
        deduped.append(candidate)
    return deduped


def _merge_candidates(
    existing: HoaContactCandidate,
    incoming: HoaContactCandidate,
) -> HoaContactCandidate:
    raw = existing.raw
    if incoming.raw and incoming.raw != existing.raw:
        raw = {"primary": existing.raw, "merged": [incoming.raw]}
    return existing.model_copy(
        update={
            "rank": min(existing.rank, incoming.rank),
            "name": existing.name or incoming.name,
            "website": existing.website or incoming.website,
            "source_url": existing.source_url or incoming.source_url,
            "address": existing.address or incoming.address,
            "phone_numbers": _unique(
                [*existing.phone_numbers, *incoming.phone_numbers]
            ),
            "email_addresses": _unique(
                [*existing.email_addresses, *incoming.email_addresses]
            ),
            "snippet": existing.snippet or incoming.snippet,
            "raw": raw,
        }
    )


def _candidate_from_mapping(
    *,
    source_type: str,
    fallback_rank: int,
    mapping: dict[str, Any],
) -> HoaContactCandidate:
    rank = _int_or_default(mapping.get("position"), fallback_rank)
    name = _string_or_none(
        mapping.get("title")
        or mapping.get("name")
        or mapping.get("business_name")
        or mapping.get("place")
    )
    website = _string_or_none(mapping.get("website") or mapping.get("link"))
    source_url = _string_or_none(mapping.get("link") or mapping.get("website"))
    address = _string_or_none(mapping.get("address") or mapping.get("street_address"))
    explicit_phone = _string_or_none(
        mapping.get("phone") or mapping.get("phone_number") or mapping.get("telephone")
    )
    snippet = _string_or_none(
        mapping.get("snippet") or mapping.get("description") or mapping.get("subtitle")
    )
    text_blob = " ".join(_candidate_text(mapping))
    phones = _explicit_phone_numbers(explicit_phone)
    phones.extend(_extract_phone_numbers(text_blob))
    emails = _extract_email_addresses(text_blob)
    return HoaContactCandidate(
        rank=rank,
        source_type=source_type,
        name=name,
        website=website,
        source_url=source_url,
        address=address,
        phone_numbers=_unique(phone for phone in phones if phone),
        email_addresses=emails,
        snippet=snippet,
        raw=_redact_serpapi_payload(mapping),
    )


def _candidate_text(mapping: dict[str, Any]) -> list[str]:
    keys = (
        "title",
        "name",
        "business_name",
        "snippet",
        "description",
        "subtitle",
        "address",
        "street_address",
        "phone",
        "phone_number",
        "telephone",
        "website",
        "link",
        "displayed_link",
        "rich_snippet",
        "rich_snippet_table",
        "sitelinks",
        "extensions",
    )
    values: list[str] = []
    for key in keys:
        values.extend(_flatten_strings(mapping.get(key)))
    return values


def _local_result_items(local_results: Any) -> list[dict[str, Any]]:
    if isinstance(local_results, list):
        return [item for item in local_results if isinstance(item, dict)]
    if isinstance(local_results, dict):
        for key in ("places", "results", "local_results"):
            value = local_results.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if local_results.get("title") or local_results.get("name"):
            return [local_results]
    return []


def _deduplicate_candidate_fields(candidate: HoaContactCandidate) -> HoaContactCandidate:
    return candidate.model_copy(
        update={
            "email_addresses": _unique(candidate.email_addresses),
            "phone_numbers": _unique(candidate.phone_numbers),
        }
    )


def _best_candidate(
    candidates: list[HoaContactCandidate],
    *,
    hoa_name: str,
) -> HoaContactCandidate | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: _candidate_quality_score(candidate, hoa_name=hoa_name),
    )


def _candidate_quality_score(candidate: HoaContactCandidate, *, hoa_name: str) -> int:
    score = max(0, 30 - candidate.rank)
    if candidate.source_type == "site_result":
        score += 70
    if candidate.email_addresses:
        score += 90
    if candidate.phone_numbers:
        score += 35
    if candidate.address:
        score += 30
    if candidate.website:
        score += 15
    if _is_contact_page(candidate):
        score += 25
    if _is_official_like(candidate, hoa_name=hoa_name):
        score += 90
    if _is_third_party_result(candidate):
        score -= 80
    return score


def _select_official_domain(
    candidates: list[HoaContactCandidate],
    *,
    hoa_name: str,
) -> str | None:
    scored: list[tuple[int, str]] = []
    tokens = _important_name_tokens(hoa_name)
    for candidate in candidates:
        host = _hostname(candidate.website or candidate.source_url)
        if not host or _is_third_party_host(host):
            continue
        score = max(0, 30 - candidate.rank)
        if _is_official_like(candidate, hoa_name=hoa_name):
            score += 90
        if tokens and any(token in host for token in tokens):
            score += 25
        if candidate.source_type in {"knowledge_graph", "local_result"}:
            score += 20
        if _is_contact_page(candidate):
            score += 10
        scored.append((score, host))
    if not scored:
        return None
    scored.sort(reverse=True)
    score, host = scored[0]
    return host if score >= 25 else None


def _is_contact_page(candidate: HoaContactCandidate) -> bool:
    haystack = " ".join(
        value
        for value in [
            candidate.name,
            candidate.website,
            candidate.source_url,
            candidate.snippet,
        ]
        if value
    ).casefold()
    return any(term in haystack for term in _CONTACT_PATH_TERMS)


def _is_official_like(candidate: HoaContactCandidate, *, hoa_name: str) -> bool:
    host = _hostname(candidate.website or candidate.source_url)
    if not host or _is_third_party_host(host):
        return False

    tokens = _important_name_tokens(hoa_name)
    if tokens and all(token in host for token in tokens[:3]):
        return True

    source = _string_or_none(candidate.raw.get("source"))
    source_text = f"{candidate.name or ''} {source or ''}".casefold()
    return bool(tokens and all(token in source_text for token in tokens[:3]))


def _is_third_party_result(candidate: HoaContactCandidate) -> bool:
    host = _hostname(candidate.website or candidate.source_url)
    return bool(host and _is_third_party_host(host))


def _is_third_party_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in _THIRD_PARTY_DOMAINS)


def _citations_for_record(record: HoaContactSearchRecord) -> list[SourceCitation]:
    citations = [
        SourceCitation(
            label="SerpAPI Google Search API",
            uri="https://serpapi.com/search-api",
            retrieved_at=record.source.get("retrieved_at"),
        )
    ]
    seen = {"https://serpapi.com/search-api"}
    for candidate in record.candidates:
        uri = candidate.source_url or candidate.website
        if not uri or uri in seen:
            continue
        seen.add(uri)
        citations.append(
            SourceCitation(
                label=candidate.name or candidate.source_type,
                uri=uri,
                retrieved_at=record.source.get("retrieved_at"),
                metadata={"source_type": candidate.source_type, "rank": candidate.rank},
            )
        )
        if len(citations) >= 6:
            break
    return citations


def _serpapi_search_summaries(searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for search in searches:
        data = search.get("data") if isinstance(search.get("data"), dict) else {}
        summaries.append(
            {
                "stage": search.get("stage") or "contact_lookup",
                "search_metadata": _redact_serpapi_payload(
                    data.get("search_metadata") or {}
                ),
                "search_parameters": _redact_serpapi_payload(
                    search.get("search_parameters") or {}
                ),
                "organic_result_count": len(data.get("organic_results") or []),
                "local_result_count": len(_local_result_items(data.get("local_results"))),
                "knowledge_graph_present": isinstance(data.get("knowledge_graph"), dict),
            }
        )
    return summaries


def _extract_email_addresses(text: str) -> list[str]:
    return _unique(match.group(0).lower().rstrip(".,;:") for match in _EMAIL_RE.finditer(text))


def _extract_phone_numbers(text: str) -> list[str]:
    return _unique(_clean_phone(match.group(0)) for match in _PHONE_RE.finditer(text))


def _explicit_phone_numbers(value: str | None) -> list[str]:
    if not value:
        return []
    extracted = _extract_phone_numbers(value)
    if extracted:
        return extracted
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return [f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"]
    if len(digits) == 11 and digits.startswith("1"):
        return [f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"]
    return []


def _clean_phone(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip(" .;,"))
    return cleaned


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_flatten_strings(item))
        return values
    if isinstance(value, list | tuple):
        values = []
        for item in value:
            values.extend(_flatten_strings(item))
        return values
    if isinstance(value, int | float | bool):
        return [str(value)]
    return []


def _state_location(state: str | None) -> str | None:
    if not state:
        return None
    if "," in state or "united states" in state.lower():
        return state
    normalized = state.strip()
    if len(normalized) == 2:
        normalized = _STATE_NAMES.get(normalized.upper(), normalized.upper())
    return f"{normalized}, United States"


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url if "://" in url else f"https://{url}"
    host = urlsplit(candidate).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _important_name_tokens(name: str) -> list[str]:
    stopwords = {"the", "hoa", "homeowner", "homeowners", "association", "assn", "inc", "llc"}
    tokens = re.findall(r"[a-z0-9]+", name.casefold())
    return [token for token in tokens if token not in stopwords and len(token) > 2]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _redact_serpapi_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_QUERY_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = _redact_serpapi_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_serpapi_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_serpapi_url(value)
    return value


def _redact_serpapi_url(value: str) -> str:
    if "api_key=" not in value:
        return value
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, "***" if key.lower() in _SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _first_result_url(record: HoaContactSearchRecord) -> str | None:
    for candidate in record.candidates:
        url = candidate.source_url or candidate.website
        if url and not _is_third_party_host(_hostname(url) or ""):
            return url
    if record.best_match:
        url = record.best_match.source_url or record.best_match.website
        if url:
            return url
    for candidate in record.candidates:
        url = candidate.source_url or candidate.website
        if url:
            return url
    return None


class _HoaPageTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _PAGE_FETCH_SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"br", "p", "div", "li", "tr"} and not self._skip_depth:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _PAGE_FETCH_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "tr", "section", "article"} and not self._skip_depth:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            if not self.title:
                stripped = data.strip()
                if stripped:
                    self.title = stripped
            return
        if self._skip_depth:
            return
        if data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        collapsed = re.sub(r"[ \t\f\v]+", " ", joined)
        collapsed = re.sub(r"\n[ \t]+", "\n", collapsed)
        collapsed = re.sub(r"\n{2,}", "\n\n", collapsed)
        return collapsed.strip()


def _fetch_page_text(url: str, *, timeout: float) -> HoaPageFetch:
    started = time.time()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _PAGE_FETCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type")
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(_PAGE_BODY_BYTE_LIMIT + 1)
            status_code = response.status
            final_url = response.geturl()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        LOGGER.warning("Failed to fetch top HOA result %s: %s", url, exc)
        return HoaPageFetch(
            url=url,
            error=str(exc),
            duration_seconds=round(time.time() - started, 3),
        )

    body_truncated = len(body) > _PAGE_BODY_BYTE_LIMIT
    if body_truncated:
        body = body[:_PAGE_BODY_BYTE_LIMIT]

    try:
        html = body.decode(charset, errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")

    extractor = _HoaPageTextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception as exc:  # html.parser raises a variety of exceptions on malformed input
        LOGGER.warning("HTML parse failed for %s: %s", url, exc)
        return HoaPageFetch(
            url=url,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            error=f"HTML parsing failed: {exc}",
            duration_seconds=round(time.time() - started, 3),
        )

    text = extractor.text()
    text_truncated = False
    if len(text) > _PAGE_TEXT_CHAR_LIMIT:
        text = text[:_PAGE_TEXT_CHAR_LIMIT]
        text_truncated = True

    return HoaPageFetch(
        url=url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        title=extractor.title,
        text=text or None,
        text_length=len(text),
        truncated=body_truncated or text_truncated,
        duration_seconds=round(time.time() - started, 3),
    )

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

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


class PacerEnvironment(StrEnum):
    PRODUCTION = "production"
    QA = "qa"


class PacerClientError(RuntimeError):
    pass


class PacerBankruptcySearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ssn: str | None = None
    ssn4: str | None = None
    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    tax_id_type: str | None = None
    business_name: str | None = None
    court_id: str | None = None
    case_number: str | None = None
    case_year_from: int | None = None
    case_year_to: int | None = None
    exact_name_match: bool = False

    @field_validator("tax_id_type")
    @classmethod
    def normalize_tax_id_type(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class PacerBankruptcyCaseRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    party_name: str
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    business_name: str | None = None
    court_id: str | None = None
    case_number: str | None = None
    case_title: str | None = None
    case_id: str | None = None
    date_filed: str | None = None
    date_terminated: str | None = None
    bankruptcy_chapter: str | None = None
    disposition_method: str | None = None
    is_open: bool
    raw: dict[str, Any] = Field(default_factory=dict)


class PacerBankruptcySearchSummary(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title_officer_review_required: bool
    text: str


class PacerBankruptcySearchRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.pacer_bankruptcy_search"
    schema_version: str = "1.0"
    record_type: str = "pacer_bankruptcy_search"
    source: dict[str, Any]
    query: dict[str, Any]
    search_criteria: dict[str, Any]
    result_count: int
    cases: list[PacerBankruptcyCaseRecord] = Field(default_factory=list)
    summary: PacerBankruptcySearchSummary
    duration_seconds: float
    source_specific: dict[str, Any] = Field(default_factory=dict)


class _PacerClientProtocol(Protocol):
    def bankruptcy_search(self, query: PacerBankruptcySearchQuery) -> PacerBankruptcySearchRecord:
        """Run a PACER bankruptcy party search."""


class PacerClient:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        client_code: str | None = None,
        qa_mode: bool = False,
        timeout: float = 30.0,
        opener: Any | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.client_code = client_code
        self.environment = PacerEnvironment.QA if qa_mode else PacerEnvironment.PRODUCTION
        self.base_url = (
            "https://qa-login.uscourts.gov"
            if qa_mode
            else "https://pacer.login.uscourts.gov"
        )
        self.pcl_base_url = (
            "https://qa-pcl.uscourts.gov/pcl-public-api/rest"
            if qa_mode
            else "https://pcl.uscourts.gov/pcl-public-api/rest"
        )
        self.timeout = timeout
        self.auth_token: str | None = None
        self._opener = opener or build_opener(HTTPCookieProcessor())

    def login(self) -> str:
        LOGGER.info("Logging in to PACER Case Locator (%s).", self.environment.value)
        payload = {
            "loginId": self.username,
            "password": self.password,
            "clientCode": self.client_code or "",
            "redactFlag": "1",
        }
        data = self._post_json(f"{self.base_url}/services/cso-auth", payload)
        if data.get("loginResult") == "0" and data.get("nextGenCSO"):
            self.auth_token = str(data["nextGenCSO"])
            LOGGER.info("PACER login succeeded.")
            return self.auth_token
        message = data.get("errorDescription") or "PACER login failed."
        raise PacerClientError(str(message))

    def logout(self) -> None:
        if not self.auth_token:
            return
        LOGGER.info("Logging out of PACER Case Locator.")
        token = self.auth_token
        self.auth_token = None
        self._post_json(f"{self.base_url}/services/cso-logout", {"nextGenCSO": token})

    def bankruptcy_search(self, query: PacerBankruptcySearchQuery) -> PacerBankruptcySearchRecord:
        start = time.time()
        query = PacerBankruptcySearchQuery.model_validate(query)
        criteria = build_bankruptcy_party_search_criteria(query)
        LOGGER.info(
            "Running PACER bankruptcy search with criteria: %s",
            redacted_criteria(criteria),
        )
        if not self.auth_token:
            self.login()

        result = self.advanced_party_search(criteria)
        result_without_receipt = dict(result)
        result_without_receipt.pop("receipt", None)
        cases = [
            _case_record_from_party(party)
            for party in result_without_receipt.get("content") or []
        ]
        summary = bankruptcy_search_summary(cases)
        retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
        LOGGER.info("PACER bankruptcy search returned %s case record(s).", len(cases))
        return PacerBankruptcySearchRecord(
            source={
                "source_id": PacerBankruptcySourceConnector.source_id,
                "source_name": "PACER Case Locator Bankruptcy Party Search",
                "environment": self.environment.value,
                "pcl_base_url": self.pcl_base_url,
                "retrieved_at": retrieved_at,
            },
            query=redacted_query(query),
            search_criteria=redacted_criteria(criteria),
            result_count=len(cases),
            cases=cases,
            summary=summary,
            duration_seconds=round(time.time() - start, 3),
            source_specific={
                "pacer": {
                    "content": result_without_receipt.get("content") or [],
                    "page": result_without_receipt.get("page"),
                    "receipt_removed": "receipt" in result,
                }
            },
        )

    def advanced_party_search(self, criteria: dict[str, Any]) -> dict[str, Any]:
        if not self.auth_token:
            raise PacerClientError("PACER authentication token is not available.")
        _validate_party_search_criteria(criteria)
        url = f"{self.pcl_base_url}/parties/find"
        LOGGER.info("Calling PACER party search endpoint.")
        return self._post_json(
            url,
            criteria,
            headers={"X-NEXT-GEN-CSO": self.auth_token},
            update_token=True,
        )

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        update_token: bool = False,
    ) -> dict[str, Any]:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if update_token:
                    next_token = response.headers.get("X-NEXT-GEN-CSO")
                    if next_token:
                        self.auth_token = next_token
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise PacerClientError(f"PACER request failed with HTTP {exc.code}.") from exc
        except URLError as exc:
            raise PacerClientError(f"PACER request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise PacerClientError("PACER returned a non-JSON response.") from exc
        if not isinstance(parsed, dict):
            raise PacerClientError("PACER returned an unexpected response shape.")
        return parsed


class PacerBankruptcySourceConnector(SourceConnector):
    source_id = "us-federal-pacer-bankruptcy"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="PACER Case Locator Bankruptcy Party Search",
        kind=SourceKind.COURT,
        jurisdiction_scope=JurisdictionScope(country="US"),
        priority=150,
        owner="Administrative Office of the U.S. Courts",
        base_url="https://pacer.uscourts.gov/",
        requires_auth=True,
        metadata={
            "api": "PACER Case Locator PCL API",
            "env_vars": [
                "TITLE_MCP_PACER_USERNAME",
                "TITLE_MCP_PACER_PASSWORD",
                "TITLE_MCP_PACER_CLIENT_CODE",
                "TITLE_MCP_PACER_QA_MODE",
            ],
            "official_docs": [
                "https://pacer.uscourts.gov/help/pacer/pacer-case-locator-pcl-api-user-guide"
            ],
        },
    )

    def __init__(
        self,
        *,
        settings: TitleMCPSettings | None = None,
        client: _PacerClientProtocol | None = None,
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
                    "Set TITLE_MCP_PACER_USERNAME and TITLE_MCP_PACER_PASSWORD in .env "
                    "before querying PACER."
                ],
                metadata={
                    "required_env_vars": [
                        "TITLE_MCP_PACER_USERNAME",
                        "TITLE_MCP_PACER_PASSWORD",
                    ]
                },
            )

        try:
            search_query = PacerBankruptcySearchQuery.model_validate(query.criteria)
            record = await asyncio.to_thread(
                client.bankruptcy_search,
                search_query,
            )
        except Exception as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"PACER bankruptcy search failed: {exc}"],
            )

        return SourceResult(
            source_id=self.source_id,
            status=(
                SourceResultStatus.SUCCEEDED
                if record.result_count
                else SourceResultStatus.NO_RESULTS
            ),
            records=[record.model_dump(mode="json")],
            citations=[
                SourceCitation(
                    label="PACER Case Locator PCL API",
                    uri="https://pacer.uscourts.gov/help/pacer/pacer-case-locator-pcl-api-user-guide",
                    retrieved_at=record.source.get("retrieved_at"),
                )
            ],
            warnings=[],
            requires_human_review=True,
            metadata={
                "canonical_schema": record.schema_name,
                "canonical_schema_version": record.schema_version,
                "result_count": record.result_count,
                "title_officer_review_required": (
                    record.summary.title_officer_review_required
                ),
            },
        )

    def _client_from_settings(self) -> PacerClient | None:
        if not self.settings.pacer_username or not self.settings.pacer_password:
            return None
        self._client = PacerClient(
            self.settings.pacer_username,
            self.settings.pacer_password,
            client_code=self.settings.pacer_client_code,
            qa_mode=self.settings.pacer_qa_mode,
            timeout=self.settings.pacer_timeout_seconds,
        )
        return self._client


def build_bankruptcy_party_search_criteria(
    query: PacerBankruptcySearchQuery,
) -> dict[str, Any]:
    tax_id_type = (query.tax_id_type or "").upper()
    criteria: dict[str, Any] = {
        "jurisdictionType": "Bankruptcy",
        "exactNameMatch": "true" if query.exact_name_match else "false",
    }
    if query.court_id:
        criteria["courtId"] = query.court_id
    if query.case_number:
        criteria["caseNumberFull"] = query.case_number
    if query.case_year_from is not None:
        criteria["caseYearFrom"] = str(query.case_year_from)
    if query.case_year_to is not None:
        criteria["caseYearTo"] = str(query.case_year_to)

    has_person_identifiers = any(
        [
            query.last_name,
            query.first_name,
            query.middle_name,
            query.ssn,
            query.ssn4,
        ]
    )
    is_entity_search = tax_id_type == "EIN" or (
        bool(query.business_name) and not has_person_identifiers
    )

    if is_entity_search:
        business_name = clean_business_name(query.business_name or "")
        if not business_name:
            raise PacerClientError("Business name is required for PACER entity searches.")
        criteria["lastName"] = business_name[:69]
        return criteria

    last_name = clean_last_name_for_pacer(query.last_name or "")
    if not last_name:
        raise PacerClientError("Last name is required for PACER person searches.")
    criteria["lastName"] = last_name
    if query.first_name:
        criteria["firstName"] = query.first_name[:32]
    if query.middle_name:
        criteria["middleName"] = query.middle_name[:32]

    ssn = normalize_ssn(query.ssn or "")
    if ssn:
        if not is_valid_ssn_deep(ssn):
            raise PacerClientError("Invalid SSN based on SSA validation rules.")
        criteria["ssn"] = ssn
    ssn4 = normalize_ssn(query.ssn4 or "")
    if ssn4:
        if not re.fullmatch(r"\d{4}", ssn4):
            raise PacerClientError("SSN4 must be exactly four digits.")
        criteria["ssn4"] = ssn4
    return criteria


def bankruptcy_search_summary(
    cases: list[PacerBankruptcyCaseRecord],
) -> PacerBankruptcySearchSummary:
    if not cases:
        return PacerBankruptcySearchSummary(
            title_officer_review_required=False,
            text=(
                "TITLE OFFICER REVIEW IS NOT REQUIRED\n\n"
                "No bankruptcy cases found for this search."
            ),
        )

    review_required = any(case.is_open for case in cases)
    review_line = (
        "TITLE OFFICER REVIEW IS REQUIRED"
        if review_required
        else "TITLE OFFICER REVIEW IS NOT REQUIRED"
    )
    detail_lines = [_case_summary_line(case) for case in cases]
    return PacerBankruptcySearchSummary(
        title_officer_review_required=review_required,
        text=f"{review_line}\n\n" + "\n".join(detail_lines),
    )


def is_valid_ssn_deep(value: str) -> bool:
    digits = normalize_ssn(value)
    if not re.fullmatch(r"\d{9}", digits):
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area == "000" or area == "666" or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return digits not in {"123456789", "219099999", "078051120"}


def normalize_ssn(value: str) -> str:
    return re.sub(r"[^\d]", "", value or "")


def clean_last_name_for_pacer(last_name: str) -> str:
    if not last_name:
        return ""
    value = last_name.strip()
    if "," in value:
        value = value.split(",", 1)[0].strip()
    if " - " in value:
        value = value.split(" - ", 1)[0].strip()
    return value[:69]


def clean_business_name(name: str) -> str:
    return name.strip()[:128] if name else ""


def redacted_query(query: PacerBankruptcySearchQuery) -> dict[str, Any]:
    payload = query.model_dump(mode="json")
    if query.ssn:
        payload["ssn"] = _redacted_ssn(query.ssn)
    if query.ssn4:
        payload["ssn4"] = "****"
    return payload


def redacted_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    payload = dict(criteria)
    if payload.get("ssn"):
        payload["ssn"] = _redacted_ssn(str(payload["ssn"]))
    if payload.get("ssn4"):
        payload["ssn4"] = "****"
    return payload


def _redacted_ssn(value: str) -> str:
    digits = normalize_ssn(value)
    return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"


def _validate_party_search_criteria(criteria: dict[str, Any]) -> None:
    valid = {
        "reportId",
        "courtId",
        "caseId",
        "caseNumberFull",
        "lastName",
        "firstName",
        "middleName",
        "generation",
        "partyType",
        "partyRole",
        "exactNameMatch",
        "caseYearFrom",
        "caseYearTo",
        "jurisdictionType",
        "ssn",
        "ssn4",
    }
    bad = set(criteria) - valid
    if bad:
        raise PacerClientError(f"Invalid PACER search keys: {', '.join(sorted(bad))}")


def _case_record_from_party(party: dict[str, Any]) -> PacerBankruptcyCaseRecord:
    court_case = party.get("courtCase") or {}
    party_name = _party_name(party)
    date_terminated = _string(court_case.get("dateTermed") or party.get("dateTermed"))
    raw = dict(party)
    raw.pop("ssn", None)
    raw.pop("ssn4", None)
    return PacerBankruptcyCaseRecord(
        party_name=party_name,
        first_name=_string(party.get("firstName")),
        middle_name=_string(party.get("middleName")),
        last_name=_string(party.get("lastName")),
        business_name=_string(party.get("businessName")),
        court_id=_string(court_case.get("courtId") or party.get("courtId")),
        case_number=_string(
            court_case.get("caseNumberFull") or party.get("caseNumberFull")
        ),
        case_title=_string(court_case.get("caseTitle") or party.get("caseTitle")),
        case_id=_string(court_case.get("caseId") or party.get("caseId")),
        date_filed=_string(court_case.get("dateFiled") or party.get("dateFiled")),
        date_terminated=date_terminated,
        bankruptcy_chapter=_string(
            court_case.get("bankruptcyChapter") or party.get("bankruptcyChapter")
        ),
        disposition_method=_string(
            court_case.get("dispositionMethod")
            or party.get("dispositionMethod")
            or party.get("disposition")
        ),
        is_open=not bool(date_terminated),
        raw=raw,
    )


def _case_summary_line(case: PacerBankruptcyCaseRecord) -> str:
    year = (case.date_filed or "")[:4]
    parts = [case.party_name]
    if case.bankruptcy_chapter:
        parts.append(f"Ch.{case.bankruptcy_chapter}")
    if case.disposition_method:
        parts.append(case.disposition_method)
    if year:
        parts.append(year)
    if case.court_id:
        parts.append(case.court_id.upper())
    if case.case_number:
        parts.append(case.case_number)
    return " - ".join(parts)


def _party_name(party: dict[str, Any]) -> str:
    name = " ".join(
        part
        for part in [
            _string(party.get("firstName")),
            _string(party.get("middleName")),
            _string(party.get("lastName")),
        ]
        if part
    )
    return name or _string(party.get("businessName")) or "Unknown party"


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

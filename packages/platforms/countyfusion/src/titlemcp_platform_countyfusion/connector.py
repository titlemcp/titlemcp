"""A CountyFusion county as a source connector."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from requests import RequestException

from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.recorder import MortgageReleaseQuery
from title_mcp.sources import (
    SourceCitation,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
    find_mortgage_release,
    release_source_result,
)
from titlemcp_platform_countyfusion.client import (
    CountyFusionClient,
    CountyFusionProtocolError,
)
from titlemcp_platform_countyfusion.config import CountyFusionSiteConfig
from titlemcp_platform_countyfusion.index import CountyFusionIndex

#: What a failed search can raise: the site refusing, or the network.
_SEARCH_FAILURES = (CountyFusionProtocolError, RequestException, OSError, TimeoutError)


class CountyFusionRecorderConnector:
    """Reads one county's public index, and looks for releases of mortgages.

    The public login needs no account, so no credential is configured. The
    only ``REQUIRES_CONFIGURATION`` path is a missing search term.
    """

    def __init__(self, config: CountyFusionSiteConfig, *, client: Any = None) -> None:
        self.config = config
        self.source_id = config.source_id
        self.descriptor = SourceDescriptor(
            source_id=config.source_id,
            name=config.name,
            kind=SourceKind.COUNTY_RECORDER,
            jurisdiction_scope=config.scope,
            priority=config.priority,
            owner=config.owner,
            base_url=config.base_url,
            requires_auth=False,
            metadata={"platform": "kofile-countyfusion"},
        )
        self._client = client or CountyFusionClient(config)

    def supports(self, jurisdiction: Jurisdiction, kind: Any = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        """Search the index by party name or instrument number."""
        criteria = query.criteria or {}
        party = str(criteria.get("party_name") or "").strip()
        number = str(criteria.get("instrument_number") or "").strip()
        if not (party or number):
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    "party_name or instrument_number is required. The county indexes by party "
                    "name, instrument number and legal description, not by street address."
                ],
            )
        try:
            if number:
                found = await self._client.search_instrument(number)
            else:
                found = await self._client.search_names(
                    party,
                    recorded_from=_date(criteria.get("recorded_from")),
                    recorded_to=_date(criteria.get("recorded_to")),
                )
        except _SEARCH_FAILURES as exc:
            return self._failed(exc)
        if not found:
            return SourceResult(source_id=self.source_id, status=SourceResultStatus.NO_RESULTS)

        retrieved_at = datetime.now(UTC).isoformat()
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=[document.model_dump(mode="json") for document in found],
            citations=[
                SourceCitation(
                    label=f"{document.document_type} {document.instrument_number}",
                    uri=self.config.base_url,
                    recording_reference=document.instrument_number,
                    retrieved_at=retrieved_at,
                )
                for document in found
            ],
            # Liens and their releases are title-impacting facts read out of an index.
            requires_human_review=True,
        )

    async def find_release(
        self, jurisdiction: Jurisdiction, query: MortgageReleaseQuery
    ) -> SourceResult:
        """Whether the county's index shows the mortgage released."""
        try:
            finding = await find_mortgage_release(CountyFusionIndex(self._client), query)
        except _SEARCH_FAILURES as exc:
            return self._failed(exc)
        return release_source_result(
            descriptor=self.descriptor,
            jurisdiction=jurisdiction,
            query=query,
            finding=finding,
        )

    def _failed(self, exc: Exception) -> SourceResult:
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.FAILED,
            warnings=[f"{type(exc).__name__}: {exc}"],
        )


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])

"""The OFAC screening source connector: lists in, candidates with reasons out."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
from title_mcp.sources.ofac.lists import ListFetcher, ListStore, changed
from title_mcp.sources.ofac.match import Screener, Thresholds
from title_mcp.sources.ofac.models import (
    ListVersion,
    OfacScreeningRecord,
    Outcome,
    PartyScreening,
    SanctionsEntry,
    SanctionsList,
    ScreeningParty,
)


class OfacScreeningQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parties: list[ScreeningParty] = Field(min_length=1, max_length=200)
    lists: list[SanctionsList] = Field(
        default_factory=lambda: [SanctionsList.SDN, SanctionsList.CONSOLIDATED]
    )
    #: Screen only against entries added or changed in the latest list version.
    changes_only: bool = False
    refresh: bool = False


class OfacScreeningSourceConnector(SourceConnector):
    source_id = "us-federal-ofac-sanctions"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="OFAC Sanctions List Screening (SDN and consolidated lists)",
        kind=SourceKind.OFFICIAL_RECORDS,
        jurisdiction_scope=JurisdictionScope(country="US"),
        priority=150,
        owner="U.S. Department of the Treasury, Office of Foreign Assets Control",
        base_url="https://sanctionslistservice.ofac.treas.gov/",
        requires_auth=False,
        metadata={
            "files": ["SDN.XML", "CONSOLIDATED.XML"],
            "env_vars": [
                "TITLE_MCP_OFAC_CACHE_DIR",
                "TITLE_MCP_OFAC_MAX_AGE_HOURS",
                "TITLE_MCP_OFAC_TIMEOUT_SECONDS",
            ],
            "official_docs": [
                "https://ofac.treasury.gov/sanctions-list-service",
                "https://ofac.treasury.gov/faqs/topic/1591",
            ],
        },
    )

    def __init__(
        self,
        *,
        settings: TitleMCPSettings | None = None,
        fetcher: ListFetcher | None = None,
        thresholds: Thresholds | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        cache = Path(self.settings.ofac_cache_dir).expanduser()
        self.store = ListStore(
            cache,
            fetcher=fetcher,
            max_age_hours=self.settings.ofac_max_age_hours,
            timeout=self.settings.ofac_timeout_seconds,
        )
        self.thresholds = thresholds or Thresholds()
        self._screeners: dict[tuple[str, ...], Screener] = {}

    def supports(self, jurisdiction: Jurisdiction, kind: SourceKind | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    def _load(self, query: OfacScreeningQuery) -> tuple[list[SanctionsEntry], list[ListVersion]]:
        entries: list[SanctionsEntry] = []
        versions: list[ListVersion] = []
        for sanctions_list in query.lists:
            found, version = self.store.load(sanctions_list, refresh=query.refresh)
            if query.changes_only:
                found = changed(self.store.previous(sanctions_list), found)
            entries.extend(found)
            versions.append(version)
        return entries, versions

    def screen(self, query: OfacScreeningQuery) -> OfacScreeningRecord:
        entries, versions = self._load(query)
        key = (*(v.sha256 for v in versions), str(query.changes_only))
        screener = self._screeners.get(key)
        if screener is None:
            screener = Screener(entries, self.thresholds)
            self._screeners = {key: screener}  # keep only the current lists' index
        parties = [_redacted(screener.screen(p)) for p in query.parties]
        outcome = (
            Outcome.POTENTIAL_MATCH
            if any(p.outcome is Outcome.POTENTIAL_MATCH for p in parties)
            else Outcome.LIKELY_FALSE_POSITIVE
            if any(p.outcome is Outcome.LIKELY_FALSE_POSITIVE for p in parties)
            else Outcome.NO_MATCH
        )
        return OfacScreeningRecord(
            screened_at=datetime.now(UTC).isoformat(),
            lists=versions,
            thresholds=self.thresholds.as_dict(),
            outcome=outcome,
            parties=parties,
            source_specific={
                "changes_only": query.changes_only,
                "entries_screened_against": len(entries),
            },
        )

    async def query(self, query: SourceQuery) -> SourceResult:
        try:
            screening = OfacScreeningQuery.model_validate(query.criteria)
        except ValueError as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"Invalid screening request: {exc}"],
            )
        try:
            record = await asyncio.to_thread(self.screen, screening)
        except Exception as exc:  # noqa: BLE001  (reported, never raised to the tool)
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[
                    f"OFAC screening failed: {exc}. The lists download from "
                    "sanctionslistservice.ofac.treas.gov; check network access or set "
                    "TITLE_MCP_OFAC_CACHE_DIR to a folder holding SDN.XML."
                ],
            )
        warnings: list[str] = []
        for version in record.lists:
            age = _age_days(version.retrieved_at)
            if age is not None and age > 2:
                warnings.append(
                    f"The {version.sanctions_list.value} list copy is {age:.0f} days old "
                    f"(published {version.publish_date}); it could not be refreshed."
                )
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=[record.model_dump(mode="json")],
            citations=[
                SourceCitation(
                    label=(
                        f"OFAC {v.sanctions_list.value.upper()} list, published "
                        f"{v.publish_date} ({v.record_count} entries)"
                    ),
                    uri=v.source_url,
                    retrieved_at=v.retrieved_at,
                    metadata={"sha256": v.sha256},
                )
                for v in record.lists
            ],
            warnings=warnings,
            requires_human_review=True,
            metadata={"outcome": record.outcome.value},
        )


def _redacted(screening: PartyScreening) -> PartyScreening:
    """The party as echoed back: a date of birth is reduced to its year (all matching uses)."""

    dob = screening.party.date_of_birth
    if dob:
        years = re.findall(r"\b(1[89]\d\d|20\d\d)\b", dob)
        party = screening.party.model_copy(update={"date_of_birth": years[0] if years else None})
        return screening.model_copy(update={"party": party})
    return screening


def _age_days(iso: str) -> float | None:
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return (datetime.now(UTC) - then).total_seconds() / 86400


def list_status(
    connector: OfacScreeningSourceConnector, *, refresh: bool = False
) -> dict[str, Any]:
    """Which publication of each list is in use, and how fresh the copy is."""

    status = []
    for sanctions_list in (SanctionsList.SDN, SanctionsList.CONSOLIDATED):
        entries, version = connector.store.load(sanctions_list, refresh=refresh)
        changes = changed(connector.store.previous(sanctions_list), entries)
        status.append(
            {
                **version.model_dump(mode="json"),
                "changed_since_previous_copy": len(changes)
                if connector.store.previous(sanctions_list)
                else None,
            }
        )
    return {"lists": status}

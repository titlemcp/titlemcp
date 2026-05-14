from __future__ import annotations

import asyncio
import os

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.sources import (
    SourceCitation,
    SourceConnector,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)
from titlemcp_us_oh_franklin_recorder.auditor import (
    FranklinAuditorClient,
    FranklinAuditorSearchQuery,
    resolve_auditor_search_mode,
)
from titlemcp_us_oh_franklin_recorder.canonical import (
    canonical_property_assessments_from_franklin_response,
)
from titlemcp_us_oh_franklin_recorder.client import FranklinRecorderClient, RecorderSearchQuery


class FranklinRecorderSourceConnector(SourceConnector):
    source_id = "us-oh-franklin-recorder"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Franklin County, Ohio Recorder",
        kind=SourceKind.COUNTY_RECORDER,
        jurisdiction_scope=JurisdictionScope(country="US", state="OH", county="Franklin County"),
        priority=220,
        owner="Franklin County Recorder",
        requires_auth=False,
    )

    def __init__(self, websocket_url: str | None = None) -> None:
        self.websocket_url = websocket_url or os.getenv(
            "TITLEMCP_US_OH_FRANKLIN_RECORDER_WS_URL"
        )

    def supports(self, jurisdiction, kind=None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        if not self.websocket_url:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    "Set TITLEMCP_US_OH_FRANKLIN_RECORDER_WS_URL before querying this source."
                ],
            )

        client = FranklinRecorderClient(self.websocket_url)
        hits = await client.search(RecorderSearchQuery.model_validate(query.criteria))
        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED if hits else SourceResultStatus.NO_RESULTS,
            records=[hit.model_dump(mode="json") for hit in hits],
            requires_human_review=True,
        )


class FranklinAuditorSourceConnector(SourceConnector):
    source_id = "us-oh-franklin-auditor"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Franklin County, Ohio Auditor Property Search",
        kind=SourceKind.TAX_AUTHORITY,
        jurisdiction_scope=JurisdictionScope(country="US", state="OH", county="Franklin County"),
        priority=230,
        owner="Franklin County Auditor",
        base_url=FranklinAuditorClient.base_url,
        requires_auth=False,
        metadata={
            "search_modes": ["address", "owner", "parid"],
            "official_search_pages": {
                "address": (
                    "https://property.franklincountyauditor.com/_web/search/"
                    "commonsearch.aspx?mode=address"
                ),
                "owner": (
                    "https://property.franklincountyauditor.com/_web/search/"
                    "commonsearch.aspx?mode=owner"
                ),
                "parid": (
                    "https://property.franklincountyauditor.com/_web/search/"
                    "commonsearch.aspx?mode=parid"
                ),
            },
        },
    )

    def __init__(self, client: FranklinAuditorClient | None = None) -> None:
        self._client = client or FranklinAuditorClient()

    def supports(self, jurisdiction, kind=None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        try:
            criteria = dict(query.criteria)
            criteria["mode"] = resolve_auditor_search_mode(
                criteria.get("mode"),
                parcel_id=criteria.get("parcel_id"),
                owner_name=criteria.get("owner_name"),
                address=criteria.get("address"),
                address_number=criteria.get("address_number"),
                street_name=criteria.get("street_name"),
            ).value
            auditor_query = FranklinAuditorSearchQuery.model_validate(criteria)
            response = await asyncio.to_thread(self._client.search, auditor_query)
        except Exception as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"Franklin County Auditor search failed: {exc}"],
            )

        records = canonical_property_assessments_from_franklin_response(
            response,
            source_id=self.source_id,
            source_name=self.descriptor.name,
            jurisdiction=query.jurisdiction,
        )
        return SourceResult(
            source_id=self.source_id,
            status=(
                SourceResultStatus.SUCCEEDED
                if records
                else SourceResultStatus.NO_RESULTS
            ),
            records=[record.model_dump(mode="json") for record in records],
            citations=[
                SourceCitation(
                    label="Franklin County Auditor Property Search",
                    uri=FranklinAuditorClient.base_url,
                    retrieved_at=response.retrieved_at,
                )
            ],
            warnings=response.warnings,
            requires_human_review=True,
            metadata={
                "canonical_schema": "title_mcp.property_assessment_record",
                "canonical_schema_version": "1.0",
                "result_count": response.result_count,
                "record_count": len(records),
                "search_mode": response.search_mode.value,
            },
        )

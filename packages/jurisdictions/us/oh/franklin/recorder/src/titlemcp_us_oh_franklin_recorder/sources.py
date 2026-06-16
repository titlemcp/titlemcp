from __future__ import annotations

import os

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.sources import (
    SourceConnector,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
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

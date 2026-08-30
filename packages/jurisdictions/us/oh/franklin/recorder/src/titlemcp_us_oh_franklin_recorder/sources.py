"""The Franklin County recorder as a source connector."""

from __future__ import annotations

from typing import Any

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.sources import (
    SourceConnector,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)
from titlemcp_us_oh_franklin_recorder import chain
from titlemcp_us_oh_franklin_recorder.client import (
    BASE_URL,
    FranklinRecorderClient,
    RecorderProtocolError,
    RecorderSearchQuery,
)


class FranklinRecorderSourceConnector(SourceConnector):
    """Reads the county's public index.

    No credential is configured or stored: the site issues a short-lived
    session cookie to anyone who asks, and that is the whole of it. So unlike
    most connectors, this one has no ``REQUIRES_CONFIGURATION`` path for
    credentials. It has one for a missing search term, because a name search
    with nothing in it would return the county.
    """

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

    def __init__(self, base_url: str = BASE_URL, *, client: Any = None) -> None:
        self._client = client or FranklinRecorderClient(base_url)

    def supports(self, jurisdiction: Any, kind: Any = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        criteria = query.criteria or {}
        party_name = str(criteria.get("party_name") or "").strip()
        parcel_id = str(criteria.get("parcel_id") or "").strip()

        if not party_name:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    "party_name is required. The county indexes by party name and legal "
                    "description, not by street address."
                ],
            )

        try:
            found = await self._client.search(
                RecorderSearchQuery(search_value=party_name, limit=int(criteria.get("limit", 50)))
            )
        except (RecorderProtocolError, OSError, TimeoutError) as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"{type(exc).__name__}: {exc}"],
            )

        if not found.documents:
            return SourceResult(source_id=self.source_id, status=SourceResultStatus.NO_RESULTS)

        records = [document.model_dump(mode="json") for document in found.documents]
        warnings: list[str] = []
        if not parcel_id:
            # Without a parcel the answer is every property this party touched.
            warnings.append(
                "No parcel_id supplied, so results span every property naming this party in "
                "the county and no chain was assembled. Pass the auditor's parcel id to scope."
            )
        else:
            built = chain.build(
                parcel_id=parcel_id, owner_name=party_name, documents=found.documents
            )
            records = [built.model_dump(mode="json")]
            warnings.extend(built.notes)

        return SourceResult(
            source_id=self.source_id,
            status=SourceResultStatus.SUCCEEDED,
            records=records,
            warnings=warnings,
            # An open lien is a title-impacting fact read out of an index that
            # does not link releases to the mortgages they discharge.
            requires_human_review=True,
        )

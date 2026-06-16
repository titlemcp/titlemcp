from __future__ import annotations

import asyncio

from title_mcp.sources import (
    SourceCitation,
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)
from titlemcp_platform_iasworld.canonical import (
    canonical_property_assessments_from_iasworld_response,
)
from titlemcp_platform_iasworld.client import IasWorldAuditorClient
from titlemcp_platform_iasworld.config import (
    IasWorldSiteConfig,
    resolve_auditor_search_mode,
)
from titlemcp_platform_iasworld.models import IasWorldAuditorSearchQuery


class IasWorldAuditorSourceConnector:
    """A :class:`title_mcp.sources.SourceConnector` for one iasWorld county.

    Instances are built from an :class:`IasWorldSiteConfig`; one connector class
    serves every county, so a new county is a config entry rather than new code.
    """

    def __init__(
        self,
        config: IasWorldSiteConfig,
        *,
        client: IasWorldAuditorClient | None = None,
    ) -> None:
        self.config = config
        self.source_id = config.source_id
        self.descriptor = SourceDescriptor(
            source_id=config.source_id,
            name=config.name,
            kind=SourceKind.TAX_AUTHORITY,
            jurisdiction_scope=config.jurisdiction_scope,
            priority=config.priority,
            owner=config.owner,
            base_url=config.base_url,
            requires_auth=False,
            metadata={
                "search_modes": ["address", "owner", "parid"],
                "official_search_pages": config.official_search_pages,
                **config.metadata,
            },
        )
        self._client = client or IasWorldAuditorClient(config)

    def supports(self, jurisdiction, kind: SourceKind | None = None) -> bool:
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
            auditor_query = IasWorldAuditorSearchQuery.model_validate(criteria)
            response = await asyncio.to_thread(self._client.search, auditor_query)
        except Exception as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"{self.config.name} search failed: {exc}"],
            )

        records = canonical_property_assessments_from_iasworld_response(
            response,
            source_id=self.source_id,
            source_name=self.config.name,
            jurisdiction=query.jurisdiction,
        )
        return SourceResult(
            source_id=self.source_id,
            status=(
                SourceResultStatus.SUCCEEDED if records else SourceResultStatus.NO_RESULTS
            ),
            records=[record.model_dump(mode="json") for record in records],
            citations=[
                SourceCitation(
                    label=self.config.name,
                    uri=self.config.base_url,
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


def build_auditor_source_connector(
    config: IasWorldSiteConfig,
    *,
    client: IasWorldAuditorClient | None = None,
) -> IasWorldAuditorSourceConnector:
    return IasWorldAuditorSourceConnector(config, client=client)

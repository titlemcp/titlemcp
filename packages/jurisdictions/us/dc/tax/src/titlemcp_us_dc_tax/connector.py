from __future__ import annotations

import asyncio

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction
from title_mcp.domain.tax import PropertyTaxQuery
from title_mcp.sources import (
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
    tax_source_result,
)
from titlemcp_us_dc_tax.client import ArcGISError, ExtractClient
from titlemcp_us_dc_tax.mapping import ssl_candidates, tax_parcel

DATASET_URL = "https://opendata.dc.gov/datasets/DCGIS::integrated-tax-system-public-extract"


class DistrictOfColumbiaTaxConnector:
    """Reads a parcel's real property tax from the District's open data extract.

    The Office of Tax and Revenue publishes its Integrated Tax System Public
    Extract every weekday under a Creative Commons Attribution 4.0 license: each
    parcel's current-year halves, ten prior years, tax sale flags and special
    assessments. It needs no credential.
    """

    source_id = "us-dc-otr-tax"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="District of Columbia Office of Tax and Revenue, Integrated Tax System Public Extract",
        kind=SourceKind.TAX_AUTHORITY,
        # The District is one taxing jurisdiction, however a caller names its county.
        jurisdiction_scope=JurisdictionScope(country="US", state="DC"),
        priority=230,
        owner="District of Columbia Office of the Chief Financial Officer",
        base_url=DATASET_URL,
        requires_auth=False,
        metadata={"license": "CC BY 4.0", "refreshed": "weekdays"},
    )

    def __init__(self, *, client: ExtractClient | None = None) -> None:
        self._client = client or ExtractClient()

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        parcel_id = str((query.criteria or {}).get("parcel_id") or "").strip()
        if not parcel_id:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=["parcel_id (the square, suffix and lot, or the SSL) is required."],
            )
        return await self.find_tax_status(query.jurisdiction, PropertyTaxQuery(parcel_id=parcel_id))

    async def find_tax_status(
        self, jurisdiction: Jurisdiction, query: PropertyTaxQuery
    ) -> SourceResult:
        candidates = ssl_candidates(query.parcel_id)
        try:
            rows = await asyncio.to_thread(self._client.parcels, candidates)
            as_of = await asyncio.to_thread(self._client.last_edited)
        except (OSError, ValueError, ArcGISError) as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"The District's tax extract could not be read: {exc}"],
            )
        by_ssl = {str(row.get("SSL") or "").upper(): row for row in rows}
        row = next((by_ssl[ssl] for ssl in candidates if ssl in by_ssl), None)
        return tax_source_result(
            descriptor=self.descriptor,
            jurisdiction=jurisdiction,
            query=query,
            parcel=tax_parcel(row, data_as_of=as_of) if row else None,
            refreshed="weekdays",
        )

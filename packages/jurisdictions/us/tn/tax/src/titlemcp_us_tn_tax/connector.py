from __future__ import annotations

import asyncio
import urllib.parse

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
from titlemcp_us_tn_tax.client import TAX_QUERY_URL, ShelbyTrusteeClient, TrusteeError
from titlemcp_us_tn_tax.mapping import tax_parcel

PARCEL_HELP = "A Shelby County parcel number is written like 092007 00072."


class ShelbyCountyTaxConnector:
    """Reads a parcel's county property tax from the Shelby County Trustee's Tax Query.

    The Tax Query's parcel page answers from a JSON endpoint: each year's bill
    with the amount billed, paid and still owed, interest and fees, the
    delinquency date, and tax sale flags. It needs no credential.
    """

    source_id = "us-tn-shelby-tax"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Shelby County Trustee, Tax Query",
        kind=SourceKind.TAX_AUTHORITY,
        jurisdiction_scope=JurisdictionScope(country="US", state="TN", county="Shelby County"),
        priority=230,
        owner="Shelby County Trustee",
        base_url=TAX_QUERY_URL,
        requires_auth=False,
    )

    def __init__(self, *, client: ShelbyTrusteeClient | None = None) -> None:
        self._client = client or ShelbyTrusteeClient()

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        parcel_id = str((query.criteria or {}).get("parcel_id") or "").strip()
        if not parcel_id:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[f"parcel_id is required. {PARCEL_HELP}"],
            )
        return await self.find_tax_status(query.jurisdiction, PropertyTaxQuery(parcel_id=parcel_id))

    async def find_tax_status(
        self, jurisdiction: Jurisdiction, query: PropertyTaxQuery
    ) -> SourceResult:
        try:
            payload = await asyncio.to_thread(self._client.parcel, query.parcel_id)
        except (OSError, ValueError, TrusteeError) as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"The Shelby County Trustee's Tax Query could not be read: {exc}"],
            )
        parcel = tax_parcel(payload, parcel_id=query.parcel_id) if payload else None
        return tax_source_result(
            descriptor=self.descriptor,
            jurisdiction=jurisdiction,
            query=query,
            parcel=parcel,
            source_url=(
                f"{TAX_QUERY_URL}Parcel?parcel={urllib.parse.quote(parcel.parcel_id)}"
                if parcel
                else None
            ),
        )

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
from titlemcp_us_ca_tax.client import LOOKUP_PAGE_URL, ContraCostaLookupClient, TaxLookupError
from titlemcp_us_ca_tax.mapping import apn_digits, tax_parcel

APN_HELP = "A Contra Costa APN is ten digits, written like 123-456-789-1."


class ContraCostaTaxConnector:
    """Reads a parcel's secured property tax from Contra Costa County's tax lookup.

    The Treasurer-Tax Collector's lookup page answers from a JSON endpoint: each
    installment of the current and prior years with its amount, the last day
    to pay it before it is delinquent, and whether it is paid. It needs no
    credential.
    """

    source_id = "us-ca-contra-costa-tax"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Contra Costa County Treasurer-Tax Collector, Tax Lookup",
        kind=SourceKind.TAX_AUTHORITY,
        jurisdiction_scope=JurisdictionScope(
            country="US", state="CA", county="Contra Costa County"
        ),
        priority=230,
        owner="Contra Costa County Treasurer-Tax Collector",
        base_url=LOOKUP_PAGE_URL,
        requires_auth=False,
    )

    def __init__(self, *, client: ContraCostaLookupClient | None = None) -> None:
        self._client = client or ContraCostaLookupClient()

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        parcel_id = str((query.criteria or {}).get("parcel_id") or "").strip()
        if not parcel_id:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[f"parcel_id is required. {APN_HELP}"],
            )
        return await self.find_tax_status(query.jurisdiction, PropertyTaxQuery(parcel_id=parcel_id))

    async def find_tax_status(
        self, jurisdiction: Jurisdiction, query: PropertyTaxQuery
    ) -> SourceResult:
        apn = apn_digits(query.parcel_id)
        if apn is None:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[f"{query.parcel_id!r} isn't an APN. {APN_HELP}"],
            )
        try:
            payload = await asyncio.to_thread(self._client.parcel, apn)
        except (OSError, ValueError, TaxLookupError) as exc:
            return SourceResult(
                source_id=self.source_id,
                status=SourceResultStatus.FAILED,
                warnings=[f"Contra Costa County's tax lookup could not be read: {exc}"],
            )
        return tax_source_result(
            descriptor=self.descriptor,
            jurisdiction=jurisdiction,
            query=query,
            parcel=tax_parcel(payload, parcel_id=apn) if payload else None,
            source_url=f"{LOOKUP_PAGE_URL}?{urllib.parse.urlencode({'apn': apn})}",
        )

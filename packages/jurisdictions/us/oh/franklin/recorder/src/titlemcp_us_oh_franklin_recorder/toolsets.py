from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from title_mcp.domain.models import Jurisdiction
from title_mcp.platform import TitleMCPPlatform
from title_mcp.sources import SourceKind, SourceQuery
from titlemcp_us_oh_franklin_recorder.auditor import resolve_auditor_search_mode
from titlemcp_us_oh_franklin_recorder.sources import FranklinAuditorSourceConnector


class FranklinAuditorToolset:
    toolset_id = "us-oh-franklin-auditor"

    def register(self, mcp: FastMCP, platform: TitleMCPPlatform) -> None:
        @mcp.tool(
            title="Franklin County Auditor Search",
            annotations=ToolAnnotations(
                title="Franklin County Auditor Search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=True,
            ),
        )
        async def franklin_county_auditor_search(
            mode: str | None = None,
            parcel_id: str | None = None,
            owner_name: str | None = None,
            address: str | None = None,
            address_number: str | None = None,
            street_name: str | None = None,
            street_direction: str | None = None,
            unit: str | None = None,
            include_details: bool = True,
            max_results: int = 10,
            max_detail_records: int = 1,
            requested_by: str = "mcp",
        ) -> dict[str, Any]:
            """Search Franklin County Auditor records and return canonical property assessments."""
            await platform.initialize()
            connector = platform.sources.get(FranklinAuditorSourceConnector.source_id)
            if connector is None:
                connector = FranklinAuditorSourceConnector()

            resolved_mode = resolve_auditor_search_mode(
                mode,
                parcel_id=parcel_id,
                owner_name=owner_name,
                address=address,
                address_number=address_number,
                street_name=street_name,
            )
            criteria = {
                "mode": resolved_mode.value,
                "parcel_id": parcel_id,
                "owner_name": owner_name,
                "address": address,
                "address_number": address_number,
                "street_name": street_name,
                "street_direction": street_direction,
                "unit": unit,
                "include_details": include_details,
                "max_results": max_results,
                "max_detail_records": max_detail_records,
            }
            criteria = {key: value for key, value in criteria.items() if value is not None}
            result = await connector.query(
                SourceQuery(
                    jurisdiction=Jurisdiction(
                        country="US",
                        state="OH",
                        county="Franklin County",
                    ),
                    kind=SourceKind.TAX_AUTHORITY,
                    criteria=criteria,
                    requested_by=requested_by,
                )
            )
            return result.model_dump(mode="json")

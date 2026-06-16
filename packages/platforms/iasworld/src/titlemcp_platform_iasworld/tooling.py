from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from title_mcp.platform import TitleMCPPlatform
from title_mcp.sources import SourceKind, SourceQuery
from titlemcp_platform_iasworld.config import (
    IasWorldSiteConfig,
    resolve_auditor_search_mode,
)
from titlemcp_platform_iasworld.factory import build_auditor_source_connector


def register_auditor_tool(
    mcp: FastMCP,
    platform: TitleMCPPlatform,
    config: IasWorldSiteConfig,
) -> None:
    """Register one ``<county>_auditor_search`` MCP tool for an iasWorld county."""

    jurisdiction = config.jurisdiction

    async def auditor_search(
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
        await platform.initialize()
        connector = platform.sources.get(config.source_id)
        if connector is None:
            connector = build_auditor_source_connector(config)

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
                jurisdiction=jurisdiction,
                kind=SourceKind.TAX_AUTHORITY,
                criteria=criteria,
                requested_by=requested_by,
            )
        )
        return result.model_dump(mode="json")

    auditor_search.__name__ = config.tool_name
    auditor_search.__qualname__ = config.tool_name
    auditor_search.__doc__ = (
        f"Search {config.name} records and return canonical property assessments "
        "(schema title_mcp.property_assessment_record)."
    )

    mcp.tool(
        name=config.tool_name,
        title=config.tool_title,
        annotations=ToolAnnotations(
            title=config.tool_title,
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )(auditor_search)

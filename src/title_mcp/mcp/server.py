from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from title_mcp.domain.models import (
    Address,
    Jurisdiction,
    ReviewDecision,
    WorkflowKind,
    WorkflowStatus,
)
from title_mcp.domain.responses import WorkflowListResponse
from title_mcp.observability import configure_logging
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings, get_settings


def _clean_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return payload or {}


def _address(
    line1: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
) -> Address | None:
    if not any([line1, city, postal_code]):
        return None
    return Address(line1=line1, city=city, state=state, postal_code=postal_code)


def create_mcp_server(
    settings: TitleMCPSettings | None = None,
    platform: TitleMCPPlatform | None = None,
) -> FastMCP:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)
    platform = platform or TitleMCPPlatform(settings=settings)

    mcp = FastMCP(
        settings.app_name,
        instructions=(
            "Tools coordinate title and real estate service workflows. "
            "They are review-first and do not make autonomous legal decisions."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    async def ensure_ready() -> None:
        await platform.initialize()

    @mcp.tool()
    async def start_title_workflow(
        kind: WorkflowKind,
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        municipality: str | None = None,
        property_line1: str | None = None,
        property_city: str | None = None,
        property_postal_code: str | None = None,
        buyer: str | None = None,
        seller: str | None = None,
        payload: dict[str, Any] | None = None,
        requested_by: str = "mcp",
        require_human_review: bool = True,
    ) -> dict[str, Any]:
        """Start a typed title operations workflow with durable state."""
        await ensure_ready()
        record = await platform.workflows.create_workflow(
            kind=kind,
            file_number=file_number,
            jurisdiction=Jurisdiction(
                country=country,
                state=state,
                county=county,
                municipality=municipality,
            ),
            property_address=_address(property_line1, property_city, state, property_postal_code),
            buyer=buyer,
            seller=seller,
            payload=_clean_payload(payload),
            requested_by=requested_by,
            require_human_review=require_human_review,
        )
        return platform.workflows.to_tool_response(
            record,
            "Workflow created. It will pause for human review when required.",
        ).model_dump(mode="json")

    @mcp.tool()
    async def analyze_document(
        file_number: str,
        document_uri: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        document_type_hint: str | None = None,
        provider: str = "aws_textract",
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a document analysis workflow for OCR/classification/extraction."""
        return await start_title_workflow(
            WorkflowKind.DOCUMENT_ANALYSIS,
            file_number,
            state,
            country=country,
            county=county,
            payload={
                "document_uri": document_uri,
                "document_type_hint": document_type_hint,
                "provider": provider,
            },
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def request_public_records_search(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        municipality: str | None = None,
        party_name: str | None = None,
        parcel_id: str | None = None,
        property_line1: str | None = None,
        property_city: str | None = None,
        property_postal_code: str | None = None,
        date_range: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a jurisdiction-routed public records search workflow."""
        return await start_title_workflow(
            WorkflowKind.PUBLIC_RECORDS_SEARCH,
            file_number,
            state,
            country=country,
            county=county,
            municipality=municipality,
            property_line1=property_line1,
            property_city=property_city,
            property_postal_code=property_postal_code,
            payload={
                "party_name": party_name,
                "parcel_id": parcel_id,
                "date_range": date_range,
            },
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def request_hoa_estoppel(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        municipality: str | None = None,
        association_name: str | None = None,
        management_company: str | None = None,
        closing_date: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a review-first HOA estoppel workflow."""
        return await start_title_workflow(
            WorkflowKind.HOA_ESTOPPEL,
            file_number,
            state,
            country=country,
            county=county,
            municipality=municipality,
            payload={
                "association_name": association_name,
                "management_company": management_company,
                "closing_date": closing_date,
            },
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def request_municipal_lien_search(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        municipality: str | None = None,
        parcel_id: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a municipal lien search workflow."""
        return await start_title_workflow(
            WorkflowKind.MUNICIPAL_LIEN_SEARCH,
            file_number,
            state,
            country=country,
            county=county,
            municipality=municipality,
            payload={"parcel_id": parcel_id},
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def request_tax_certificate(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        parcel_id: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a tax certificate workflow."""
        return await start_title_workflow(
            WorkflowKind.TAX_CERTIFICATE,
            file_number,
            state,
            country=country,
            county=county,
            payload={"parcel_id": parcel_id},
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def track_release(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        lender: str | None = None,
        recording_reference: str | None = None,
        payoff_date: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a lien or mortgage release tracking workflow."""
        return await start_title_workflow(
            WorkflowKind.RELEASE_TRACKING,
            file_number,
            state,
            country=country,
            county=county,
            payload={
                "lender": lender,
                "recording_reference": recording_reference,
                "payoff_date": payoff_date,
            },
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def parse_payoff_letter(
        file_number: str,
        document_uri: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        lender: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a payoff letter parsing workflow."""
        return await start_title_workflow(
            WorkflowKind.PAYOFF_PARSING,
            file_number,
            state,
            country=country,
            county=county,
            payload={"document_uri": document_uri, "lender": lender},
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def generate_checklist_packet(
        file_number: str,
        state: str,
        country: str = "US",
        county: str | None = None,
        transaction_type: str | None = None,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Create a checklist and packet generation workflow."""
        return await start_title_workflow(
            WorkflowKind.CHECKLIST_PACKET,
            file_number,
            state,
            country=country,
            county=county,
            payload={"transaction_type": transaction_type},
            requested_by=requested_by,
            require_human_review=True,
        )

    @mcp.tool()
    async def get_workflow_status(workflow_id: str) -> dict[str, Any]:
        """Return full workflow state, tasks, review status, and audit events."""
        await ensure_ready()
        record = await platform.workflows.get_workflow(workflow_id)
        return platform.workflows.to_tool_response(
            record,
            "Workflow status loaded.",
        ).model_dump(mode="json")

    @mcp.tool()
    async def list_workflows(
        file_number: str | None = None,
        status: WorkflowStatus | None = None,
        kind: WorkflowKind | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List recent workflows using optional file, status, or kind filters."""
        await ensure_ready()
        records = await platform.workflows.list_workflows(
            file_number=file_number,
            status=status,
            kind=kind,
            limit=limit,
        )
        return WorkflowListResponse(
            workflows=[platform.workflows.summarize(record) for record in records]
        ).model_dump(mode="json")

    @mcp.tool()
    async def submit_human_review(
        workflow_id: str,
        decision: ReviewDecision,
        reviewer: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record human review approval, rejection, or requested changes for a workflow."""
        await ensure_ready()
        record = await platform.workflows.submit_review(
            workflow_id=workflow_id,
            decision=decision,
            reviewer=reviewer,
            notes=notes,
        )
        return platform.workflows.to_tool_response(
            record,
            "Human review recorded.",
        ).model_dump(mode="json")

    return mcp


def main() -> None:
    settings = get_settings()
    server = create_mcp_server(settings)
    server.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from title_mcp.capabilities import CapabilityType
from title_mcp.domain.models import (
    Address,
    Jurisdiction,
    ReviewDecision,
    WorkflowKind,
    WorkflowStatus,
)
from title_mcp.domain.responses import WorkflowListResponse
from title_mcp.platform import TitleMCPPlatform
from title_mcp.sources import (
    HoaContactSerpApiSourceConnector,
    PacerBankruptcySourceConnector,
    RegridParcelSourceConnector,
    SourceKind,
    SourceQuery,
)
from title_mcp.vendors import VendorKind


def register_core_tools(mcp: FastMCP, platform: TitleMCPPlatform) -> None:
    """Register the core TitleMCP tool surface on a FastMCP server."""

    async def ensure_ready() -> None:
        await platform.initialize()

    @mcp.tool()
    async def hoa_contact_search(
        hoa_name: str,
        state: str | None = None,
        max_results: int = 10,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """
        Search for HOA contact information by association name and optional state.

        Returns SerpAPI Google search candidates plus the fetched page text of
        the top result under records[0].first_result_page.text. Use that page
        text as the primary source to extract structured contact details
        (HOA name, management company, mailing address, phone numbers, email
        addresses, website). The candidate-level fields are best-effort
        snippet extractions and may miss values present on the live page.
        """
        await ensure_ready()
        connector = platform.sources.get(HoaContactSerpApiSourceConnector.source_id)
        if connector is None:
            connector = HoaContactSerpApiSourceConnector(settings=platform.settings)

        criteria: dict[str, Any] = {
            "hoa_name": hoa_name,
            "state": state,
            "max_results": max_results,
        }
        criteria = {key: value for key, value in criteria.items() if value is not None}
        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.HOA,
                criteria=criteria,
                requested_by=requested_by,
            )
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def regrid_parcel_lookup(
        address: str,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Lookup parcel information by address using Regrid through the smart proxy."""
        await ensure_ready()
        connector = platform.sources.get(RegridParcelSourceConnector.source_id)
        if connector is None:
            connector = RegridParcelSourceConnector(settings=platform.settings)
        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.VENDOR_API,
                criteria={"address": address},
                requested_by=requested_by,
            )
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def pacer_bankruptcy_search(
        last_name: str | None = None,
        ssn: str | None = None,
        ssn4: str | None = None,
        first_name: str | None = None,
        middle_name: str | None = None,
        tax_id_type: str | None = None,
        business_name: str | None = None,
        court_id: str | None = None,
        case_number: str | None = None,
        case_year_from: int | None = None,
        case_year_to: int | None = None,
        exact_name_match: bool = False,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """
        Search PACER Case Locator bankruptcy party records for a person or business.

        For business/entity searches, pass business_name; tax_id_type is optional unless
        the caller explicitly knows the identifier type.
        """
        await ensure_ready()
        connector = platform.sources.get(PacerBankruptcySourceConnector.source_id)
        if connector is None:
            connector = PacerBankruptcySourceConnector(settings=platform.settings)

        criteria = {
            "last_name": last_name,
            "ssn": ssn,
            "ssn4": ssn4,
            "first_name": first_name,
            "middle_name": middle_name,
            "tax_id_type": tax_id_type,
            "business_name": business_name,
            "court_id": court_id,
            "case_number": case_number,
            "case_year_from": case_year_from,
            "case_year_to": case_year_to,
            "exact_name_match": exact_name_match,
        }
        criteria = {key: value for key, value in criteria.items() if value is not None}
        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.COURT,
                criteria=criteria,
                requested_by=requested_by,
            )
        )
        return result.model_dump(mode="json")

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
            payload=payload or {},
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

    @mcp.tool()
    async def list_title_capabilities(
        country: str | None = None,
        state: str | None = None,
        county: str | None = None,
        municipality: str | None = None,
        kind: WorkflowKind | None = None,
        capability_type: CapabilityType | None = None,
    ) -> dict[str, Any]:
        """List installed TitleMCP capability manifests, optionally filtered by scope."""
        await ensure_ready()
        if any([country, state, county, municipality]):
            jurisdiction = Jurisdiction(
                country=country or "US",
                state=state,
                county=county,
                municipality=municipality,
            )
            capabilities = platform.capabilities.resolve(
                jurisdiction,
                kind=kind,
                capability_type=capability_type,
            )
        else:
            capabilities = platform.capabilities.all()
            if kind:
                capabilities = [
                    capability
                    for capability in capabilities
                    if not capability.workflow_kinds or kind in capability.workflow_kinds
                ]
            if capability_type:
                capabilities = [
                    capability
                    for capability in capabilities
                    if capability_type in capability.capability_types
                ]

        return {
            "capabilities": [
                capability.model_dump(mode="json") for capability in capabilities
            ]
        }

    @mcp.tool()
    async def list_source_connectors(
        country: str | None = None,
        state: str | None = None,
        county: str | None = None,
        municipality: str | None = None,
        source_kind: SourceKind | None = None,
    ) -> dict[str, Any]:
        """List installed source connectors for public records, governments, OCR, and data."""
        await ensure_ready()
        jurisdiction = (
            Jurisdiction(
                country=country or "US",
                state=state,
                county=county,
                municipality=municipality,
            )
            if any([country, state, county, municipality])
            else None
        )
        connectors = [
            connector
            for connector in platform.sources.all()
            if jurisdiction is None or connector.supports(jurisdiction, source_kind)
        ]
        if source_kind and jurisdiction is None:
            connectors = [
                connector
                for connector in connectors
                if connector.descriptor.kind == source_kind
            ]

        return {
            "sources": [
                connector.descriptor.model_dump(mode="json") for connector in connectors
            ]
        }

    @mcp.tool()
    async def list_vendor_connectors(
        country: str | None = None,
        state: str | None = None,
        county: str | None = None,
        municipality: str | None = None,
        vendor_kind: VendorKind | None = None,
    ) -> dict[str, Any]:
        """List installed service-provider connectors for title operations."""
        await ensure_ready()
        jurisdiction = (
            Jurisdiction(
                country=country or "US",
                state=state,
                county=county,
                municipality=municipality,
            )
            if any([country, state, county, municipality])
            else None
        )
        connectors = [
            connector
            for connector in platform.vendors.all()
            if jurisdiction is None or connector.supports(jurisdiction, vendor_kind)
        ]
        if vendor_kind and jurisdiction is None:
            connectors = [
                connector
                for connector in connectors
                if connector.descriptor.kind == vendor_kind
            ]

        return {
            "vendors": [
                connector.descriptor.model_dump(mode="json") for connector in connectors
            ]
        }


def _address(
    line1: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
) -> Address | None:
    if not any([line1, city, postal_code]):
        return None
    return Address(line1=line1, city=city, state=state, postal_code=postal_code)

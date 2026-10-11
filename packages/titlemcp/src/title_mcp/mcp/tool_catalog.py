from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from title_mcp.capabilities import CapabilityType
from title_mcp.domain.models import (
    US_STATE_NAMES,
    Address,
    Jurisdiction,
    ReviewDecision,
    WorkflowKind,
    WorkflowStatus,
)
from title_mcp.domain.recorder import MortgageReleaseQuery
from title_mcp.domain.responses import WorkflowListResponse
from title_mcp.domain.tax import PropertyTaxQuery
from title_mcp.platform import TitleMCPPlatform
from title_mcp.sources import (
    HoaContactSerpApiSourceConnector,
    MortgageReleaseSource,
    OfacScreeningSourceConnector,
    PacerBankruptcySourceConnector,
    PropertyTaxSource,
    RegridParcelSourceConnector,
    ScreeningParty,
    SourceKind,
    SourceQuery,
    SourceResult,
    SourceResultStatus,
)
from title_mcp.vendors import VendorKind


def register_core_tools(mcp: MCPServer, platform: TitleMCPPlatform) -> None:
    """Register the core TitleMCP tool surface on a MCPServer server."""

    async def ensure_ready() -> None:
        await platform.initialize()

    @mcp.tool(
        title="HOA Contact Search",
        annotations=_read_only_open_world("HOA Contact Search"),
    )
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

    @mcp.tool(
        title="Parcel Lookup",
        annotations=_read_only_open_world("Parcel Lookup"),
    )
    async def parcel_lookup(
        address: str,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """Lookup parcel information by address."""
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
        return _public_parcel_lookup_result(result.model_dump(mode="json"))

    @mcp.tool(
        title="PACER Bankruptcy Search",
        annotations=_read_only_open_world("PACER Bankruptcy Search"),
    )
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

    @mcp.tool(
        title="OFAC Sanctions Screening",
        annotations=_read_only_open_world("OFAC Sanctions Screening"),
    )
    async def ofac_screen_parties(
        parties: list[ScreeningParty],
        changes_only: bool = False,
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """
        Screen people and companies against OFAC's sanctions lists (the PATRIOT search).

        Each party is {"name", "party_type": "individual" | "entity" | "unknown",
        "date_of_birth" (optional), "role" (optional), "reference" (optional)}. Returns a
        title_mcp.ofac_screening record: for each party an outcome (potential_match,
        likely_false_positive or no_match) and its candidates, each with the listed and
        matched names, the score and the reasons for it, against the SDN and consolidated
        lists as published on the dates cited. Nothing is cleared automatically: a
        potential match needs a person's review. Set changes_only to re-screen parties
        against only the entries added or changed in the latest list.
        """
        await ensure_ready()
        connector = platform.sources.get(OfacScreeningSourceConnector.source_id)
        if connector is None:
            connector = OfacScreeningSourceConnector(settings=platform.settings)
        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.OFFICIAL_RECORDS,
                criteria={
                    "parties": [p.model_dump(mode="json") for p in parties],
                    "changes_only": changes_only,
                },
                requested_by=requested_by,
            )
        )
        return result.model_dump(mode="json")

    @mcp.tool(
        title="OFAC List Status",
        annotations=_read_only_open_world("OFAC List Status"),
    )
    async def ofac_list_status(refresh: bool = False) -> dict[str, Any]:
        """
        Which publication of OFAC's SDN and consolidated lists screening uses: publish
        date, entry count, file hash, when the copy was fetched, and how many entries
        changed since the previous copy. Set refresh to fetch the latest lists now.
        """
        import asyncio

        from title_mcp.sources.ofac.source import list_status

        await ensure_ready()
        connector = platform.sources.get(OfacScreeningSourceConnector.source_id)
        if not isinstance(connector, OfacScreeningSourceConnector):
            connector = OfacScreeningSourceConnector(settings=platform.settings)
        return await asyncio.to_thread(list_status, connector, refresh=refresh)

    @mcp.tool(
        title="Start Title Workflow",
        annotations=_state_changing("Start Title Workflow"),
    )
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

    @mcp.tool(
        title="Analyze Document",
        annotations=_state_changing("Analyze Document"),
    )
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

    @mcp.tool(
        title="Request Public Records Search",
        annotations=_state_changing("Request Public Records Search"),
    )
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

    @mcp.tool(
        title="Request HOA Estoppel",
        annotations=_state_changing("Request HOA Estoppel"),
    )
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

    @mcp.tool(
        title="Request Municipal Lien Search",
        annotations=_state_changing("Request Municipal Lien Search"),
    )
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

    @mcp.tool(
        title="Request Tax Certificate",
        annotations=_state_changing("Request Tax Certificate"),
    )
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

    @mcp.tool(
        title="Track Release",
        annotations=_state_changing("Track Release"),
    )
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

    @mcp.tool(
        title="Mortgage Release Search",
        annotations=_read_only_open_world("Mortgage Release Search"),
    )
    async def mortgage_release_search(
        state: str,
        county: str,
        mortgage_instrument_number: str | None = None,
        mortgage_book: str | None = None,
        mortgage_page: str | None = None,
        borrower_names: list[str] | None = None,
        lender_names: list[str] | None = None,
        paid_off_on: str | None = None,
        country: str = "US",
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """
        Check a county recorder's index for the release of one mortgage.

        Pass the mortgage's instrument number, or its book and page, as the title
        commitment lists it; borrower and lender names are a fallback, and
        paid_off_on (YYYY-MM-DD) flags a release recorded before the payoff.
        Returns a title_mcp.mortgage_release_search record under records[0].
        Its status is released, partially_released, candidates_only,
        not_released or mortgage_not_found, and each release carries the basis
        for the match: the county's own index linking it to the mortgage, its
        text citing the mortgage, or only the same parties. A status of
        requires_configuration means no installed recorder connector covers
        the county, or nothing was given to search for.
        """
        await ensure_ready()
        try:
            jurisdiction = Jurisdiction(
                country=country, state=_state_code(state), county=_county_name(county)
            )
        except ValidationError:
            return _unreadable_state("mortgage-release-search", state)
        connector = _release_source(platform, jurisdiction)
        if connector is None:
            return SourceResult(
                source_id="mortgage-release-search",
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    f"No installed recorder connector checks releases for "
                    f"{jurisdiction.county}, {jurisdiction.state}."
                ],
            ).model_dump(mode="json")
        try:
            query = MortgageReleaseQuery(
                mortgage_instrument_number=mortgage_instrument_number,
                mortgage_book=mortgage_book,
                mortgage_page=mortgage_page,
                borrower_names=borrower_names or [],
                lender_names=lender_names or [],
                paid_off_on=paid_off_on,
            )
        except ValidationError as exc:
            return SourceResult(
                source_id=connector.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[error["msg"] for error in exc.errors()],
            ).model_dump(mode="json")
        result = await connector.find_release(jurisdiction, query)
        return result.model_dump(mode="json")

    @mcp.tool(
        title="Property Tax Status Search",
        annotations=_read_only_open_world("Property Tax Status Search"),
    )
    async def property_tax_status_search(
        state: str,
        county: str,
        parcel_id: str,
        country: str = "US",
        requested_by: str = "mcp",
    ) -> dict[str, Any]:
        """
        Read one parcel's current property tax status from the collector's record.

        Pass the parcel or account number the way the county's collector writes
        it. Returns a title_mcp.property_tax_status record under records[0]:
        each tax year's billed, paid and balance amounts, with installments and
        due dates where the collector gives them. Its status is paid, due,
        past_due, unknown or parcel_not_found, and source.data_as_of says how
        current the collector's data is. A status of requires_configuration
        means no installed tax connector covers the county.
        """
        await ensure_ready()
        try:
            connector, jurisdiction = _tax_source(platform, country, state, county)
        except ValidationError:
            return _unreadable_state("property-tax-status-search", state)
        if connector is None:
            return SourceResult(
                source_id="property-tax-status-search",
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[
                    f"No installed tax connector reads property tax status for "
                    f"{jurisdiction.county}, {jurisdiction.state}."
                ],
            ).model_dump(mode="json")
        try:
            query = PropertyTaxQuery(parcel_id=parcel_id)
        except ValidationError as exc:
            return SourceResult(
                source_id=connector.source_id,
                status=SourceResultStatus.REQUIRES_CONFIGURATION,
                warnings=[error["msg"] for error in exc.errors()],
            ).model_dump(mode="json")
        result = await connector.find_tax_status(jurisdiction, query)
        return result.model_dump(mode="json")

    @mcp.tool(
        title="Parse Payoff Letter",
        annotations=_state_changing("Parse Payoff Letter"),
    )
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

    @mcp.tool(
        title="Generate Checklist Packet",
        annotations=_state_changing("Generate Checklist Packet"),
    )
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

    @mcp.tool(
        title="Get Workflow Status",
        annotations=_read_only_local("Get Workflow Status"),
    )
    async def get_workflow_status(workflow_id: str) -> dict[str, Any]:
        """Return full workflow state, tasks, review status, and audit events."""
        await ensure_ready()
        record = await platform.workflows.get_workflow(workflow_id)
        return platform.workflows.to_tool_response(
            record,
            "Workflow status loaded.",
        ).model_dump(mode="json")

    @mcp.tool(
        title="List Workflows",
        annotations=_read_only_local("List Workflows"),
    )
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

    @mcp.tool(
        title="Submit Human Review",
        annotations=_state_changing("Submit Human Review"),
    )
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

    @mcp.tool(
        title="List Title Capabilities",
        annotations=_read_only_local("List Title Capabilities"),
    )
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

        return {"capabilities": [capability.model_dump(mode="json") for capability in capabilities]}

    @mcp.tool(
        title="List Source Connectors",
        annotations=_read_only_local("List Source Connectors"),
    )
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
                connector for connector in connectors if connector.descriptor.kind == source_kind
            ]

        return {
            "sources": [connector.descriptor.model_dump(mode="json") for connector in connectors]
        }

    @mcp.tool(
        title="List Vendor Connectors",
        annotations=_read_only_local("List Vendor Connectors"),
    )
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
                connector for connector in connectors if connector.descriptor.kind == vendor_kind
            ]

        return {
            "vendors": [connector.descriptor.model_dump(mode="json") for connector in connectors]
        }


def _county_name(county: str) -> str:
    """Recorder connectors are scoped to "Cuyahoga County"; callers often say "Cuyahoga"."""
    name = " ".join(county.split())
    if name.lower().endswith((" county", " parish", " borough")):
        return name
    return f"{name} County"


def _release_source(
    platform: TitleMCPPlatform, jurisdiction: Jurisdiction
) -> MortgageReleaseSource | None:
    for connector in platform.sources.all():
        if isinstance(connector, MortgageReleaseSource) and connector.supports(
            jurisdiction, SourceKind.COUNTY_RECORDER
        ):
            return connector
    return None


def _unreadable_state(source_id: str, state: str) -> dict[str, Any]:
    return SourceResult(
        source_id=source_id,
        status=SourceResultStatus.REQUIRES_CONFIGURATION,
        warnings=[f"{state!r} isn't a state; give its two-letter code, such as OH or DC."],
    ).model_dump(mode="json")


def _state_code(state: str) -> str:
    """A state's two-letter code, given the code or the name ("Ohio")."""
    name = " ".join(state.split())
    for code, full_name in US_STATE_NAMES.items():
        if name.lower() == full_name.lower():
            return code
    return name


def _tax_source(
    platform: TitleMCPPlatform, country: str, state: str, county: str
) -> tuple[PropertyTaxSource | None, Jurisdiction]:
    """The tax connector for a county, named either way ("Hennepin" or "District of Columbia")."""
    as_given = " ".join(county.split())
    candidates = [
        Jurisdiction(country=country, state=_state_code(state), county=name)
        for name in dict.fromkeys([_county_name(county), as_given])
    ]
    for jurisdiction in candidates:
        for connector in platform.sources.all():
            if isinstance(connector, PropertyTaxSource) and connector.supports(
                jurisdiction, SourceKind.TAX_AUTHORITY
            ):
                return connector, jurisdiction
    return None, candidates[0]


def _read_only_open_world(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )


def _public_parcel_lookup_result(result: dict[str, Any]) -> dict[str, Any]:
    result = dict(result)
    result["source_id"] = "parcel-lookup"
    result["citations"] = [
        {**citation, "label": "Parcel Lookup", "uri": None}
        for citation in result.get("citations", [])
        if isinstance(citation, dict)
    ]
    result["warnings"] = [
        _hide_parcel_provider_name(warning) for warning in result.get("warnings", [])
    ]

    public_records: list[dict[str, Any]] = []
    for record in result.get("records", []):
        if not isinstance(record, dict):
            continue
        public_record = dict(record)
        source = public_record.get("source")
        if isinstance(source, dict):
            public_record["source"] = {
                **source,
                "source_id": "parcel-lookup",
                "source_name": "Parcel Lookup",
                "source_url": None,
            }
        public_record.pop("source_specific", None)
        public_records.append(public_record)
    result["records"] = public_records
    return result


def _hide_parcel_provider_name(value: Any) -> str:
    return (
        str(value)
        .replace("Regrid parcel lookup", "Parcel lookup")
        .replace("Regrid Parcel Search", "Parcel Lookup")
    )


def _read_only_local(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def _state_changing(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )


def _address(
    line1: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
) -> Address | None:
    if not any([line1, city, postal_code]):
        return None
    return Address(line1=line1, city=city, state=state, postal_code=postal_code)

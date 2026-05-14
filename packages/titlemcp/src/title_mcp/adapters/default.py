from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import (
    Jurisdiction,
    RiskLevel,
    WorkflowAction,
    WorkflowKind,
    WorkflowRequest,
)

_GENERIC_STEPS: dict[WorkflowKind, list[tuple[str, str]]] = {
    WorkflowKind.DOCUMENT_ANALYSIS: [
        ("Capture document source", "Record source URI and expected document type."),
        ("Run extraction provider", "Use configured OCR/extraction provider when available."),
        (
            "Review extracted facts",
            "Human reviewer confirms material fields before downstream use.",
        ),
    ],
    WorkflowKind.PUBLIC_RECORDS_SEARCH: [
        ("Resolve recording authority", "Confirm county, city, and public-record source."),
        ("Prepare search criteria", "Collect party names, parcel, address, and date range."),
        ("Run configured search", "Use the jurisdiction-specific public-record source."),
        ("Review hits", "Human reviewer confirms matches before downstream use."),
    ],
    WorkflowKind.HOA_ESTOPPEL: [
        ("Identify association", "Confirm HOA or management company from order documents."),
        ("Prepare request packet", "Gather property, owner, closing, and authorization details."),
        ("Track external response", "Monitor received estoppel, fees, expiration, and exceptions."),
    ],
    WorkflowKind.MUNICIPAL_LIEN_SEARCH: [
        ("Resolve municipality", "Confirm municipality and utility providers for the property."),
        ("Submit search request", "Route request through configured municipal channel."),
        (
            "Review search result",
            "Reviewer validates open permits, code liens, and utility balances.",
        ),
    ],
    WorkflowKind.TAX_CERTIFICATE: [
        ("Identify tax authority", "Resolve tax collector or county source for the parcel."),
        ("Request certificate", "Submit request using configured authority-specific channel."),
        (
            "Validate taxes due",
            "Reviewer confirms taxes, discounts, delinquencies, and exemptions.",
        ),
    ],
    WorkflowKind.RELEASE_TRACKING: [
        ("Capture paid lien", "Record lender, recording data, payoff, and expected release date."),
        ("Schedule follow-up", "Create follow-up milestones until release is recorded."),
        ("Verify recording", "Reviewer confirms release document matches the satisfied lien."),
    ],
    WorkflowKind.PAYOFF_PARSING: [
        (
            "Extract payoff fields",
            "Parse lender, good-through date, per diem, and wire instructions.",
        ),
        (
            "Flag risk fields",
            "Highlight conflicting dates, wiring changes, and missing authorizations.",
        ),
        ("Reviewer approval", "Human reviewer confirms extracted payoff terms before use."),
    ],
    WorkflowKind.TITLE_CURATIVE: [
        ("Summarize defect", "Capture curative issue, affected parties, and source document."),
        ("Suggest evidence requests", "Draft reviewer-facing evidence and document requests."),
        ("Escalate for decision", "Route legal or underwriting decisions to authorized personnel."),
    ],
    WorkflowKind.DOCUMENT_CLASSIFICATION: [
        (
            "Classify document",
            "Classify uploaded document against configured title operation taxonomy.",
        ),
        ("Extract candidate fields", "Extract fields relevant to the classification."),
        ("Review classification", "Reviewer approves classification before workflow routing."),
    ],
    WorkflowKind.CHECKLIST_PACKET: [
        ("Assemble checklist", "Generate jurisdiction and transaction specific checklist items."),
        ("Collect packet inputs", "Identify required documents and unresolved dependencies."),
        ("Reviewer signoff", "Human reviewer confirms packet completeness."),
    ],
    WorkflowKind.STATUS_TRACKING: [
        ("Normalize status", "Convert vendor or system status into internal status vocabulary."),
        ("Identify blockers", "Flag missing documents, external waits, or review requirements."),
        ("Publish update", "Prepare status update for downstream systems or staff."),
    ],
}


class GenericTitleAdapter:
    adapter_id = "generic"
    priority = 0
    workflow_kinds: frozenset[WorkflowKind] | None = None

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return True

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        steps = [
            WorkflowAction(label=label, description=description)
            for label, description in _GENERIC_STEPS[request.kind]
        ]
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=request.jurisdiction,
            kind=request.kind,
            required_review=request.require_human_review,
            risk_level=RiskLevel.MEDIUM,
            steps=steps,
            warnings=[
                "Generic adapter selected; configure a jurisdiction adapter for production routing."
            ],
        )


class FloridaTitleAdapter(GenericTitleAdapter):
    adapter_id = "florida"
    priority = 50
    scope = JurisdictionScope(country="US", state="FL")

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return self.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        plan = await super().plan(request)
        plan.adapter_id = self.adapter_id
        plan.warnings = []

        if request.kind == WorkflowKind.MUNICIPAL_LIEN_SEARCH:
            plan.external_requirements.extend(
                [
                    "Confirm city, unincorporated county, and special district boundaries.",
                    "Check open permit and code enforcement sources separately where required.",
                ]
            )
        elif request.kind == WorkflowKind.TAX_CERTIFICATE:
            plan.external_requirements.append(
                "Confirm county tax collector source and parcel or alternate key before request."
            )
        elif request.kind == WorkflowKind.HOA_ESTOPPEL:
            plan.external_requirements.append(
                "Confirm statutory estoppel fee, rush fee, and association contact before "
                "submission."
            )
        elif request.kind == WorkflowKind.RELEASE_TRACKING:
            plan.external_requirements.append(
                "Track mortgage satisfaction recording against county official records."
            )

        plan.routing_hints["state"] = "FL"
        if request.jurisdiction.county:
            plan.routing_hints["county"] = request.jurisdiction.county
        return plan


class BaltimoreCityPublicRecordsAdapter(GenericTitleAdapter):
    adapter_id = "us-md-baltimore-city-public-records"
    priority = 140
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})
    scope = JurisdictionScope(
        country="US",
        state="MD",
        county="Baltimore",
        municipality="Baltimore City",
    )

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return self.scope.matches(jurisdiction)

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=request.jurisdiction,
            kind=request.kind,
            required_review=request.require_human_review,
            risk_level=RiskLevel.MEDIUM,
            steps=[
                WorkflowAction(
                    label="Search Baltimore City land records",
                    description=(
                        "Use the Maryland land records path appropriate for Baltimore City."
                    ),
                    metadata={"source": "maryland_land_records", "jurisdiction": "Baltimore City"},
                ),
                WorkflowAction(
                    label="Search Baltimore City court and lien indexes",
                    description=(
                        "Check city-specific judgment, tax sale, lien, and court-related sources."
                    ),
                    metadata={"source": "baltimore_city_public_records"},
                ),
                WorkflowAction(
                    label="Review public-record matches",
                    description="Reviewer confirms party, property, and recording-data matches.",
                ),
            ],
            external_requirements=[
                "Confirm whether the property is Baltimore City rather than Baltimore County.",
                "Capture book/page, instrument number, party name, and parcel references.",
            ],
            routing_hints={
                "country": "US",
                "state": "MD",
                "county": "Baltimore",
                "municipality": "Baltimore City",
            },
        )


class MiamiDadePublicRecordsAdapter(GenericTitleAdapter):
    adapter_id = "us-fl-miami-dade-public-records"
    priority = 150
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return jurisdiction.matches(country="US", state="FL") and (
            jurisdiction.matches(county="Miami-Dade")
            or jurisdiction.matches(county="Dade")
        )

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=request.jurisdiction,
            kind=request.kind,
            required_review=request.require_human_review,
            risk_level=RiskLevel.MEDIUM,
            steps=[
                WorkflowAction(
                    label="Search Miami-Dade official records",
                    description=(
                        "Use Miami-Dade specific official records search parameters and indexes."
                    ),
                    metadata={"source": "miami_dade_official_records"},
                ),
                WorkflowAction(
                    label="Check county civil and municipal sources",
                    description=(
                        "Review Miami-Dade county-specific civil, code, permit, and lien sources."
                    ),
                    metadata={"source": "miami_dade_county_sources"},
                ),
                WorkflowAction(
                    label="Review public-record matches",
                    description="Reviewer confirms party, property, and recording-data matches.",
                ),
            ],
            external_requirements=[
                "Normalize Dade County aliases to Miami-Dade for modern source routing.",
                "Confirm municipality because municipal sources vary inside Miami-Dade County.",
            ],
            routing_hints={
                "country": "US",
                "state": "FL",
                "county": "Miami-Dade",
            },
        )

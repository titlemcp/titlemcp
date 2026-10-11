from __future__ import annotations

from title_mcp.adapters.base import AdapterPlan, JurisdictionScope
from title_mcp.domain.models import (
    Jurisdiction,
    RiskLevel,
    WorkflowAction,
    WorkflowKind,
    WorkflowRequest,
)
from title_mcp.domain.municipal import (
    AssessmentBilling,
    BalanceRequest,
    LienCoverage,
    LienOrderChannel,
    MunicipalOffice,
    Offered,
)
from titlemcp_us_fl_municipal.directory import (
    FloridaDirectory,
    is_unincorporated,
    load_directory,
)

_CODE = {LienCoverage.CODE_VIOLATIONS, LienCoverage.CODE_LIENS}


class FloridaMunicipalLienSearchAdapter:
    """Plans a Florida municipal lien search from the government's own process.

    The steps name who issues the parcel's lien letter and how to order it, then
    add a step for each of permits, code cases and utility balances the letter
    doesn't cover, and for special assessments.
    """

    adapter_id = "us-fl-municipal-lien-search"
    priority = 120
    workflow_kinds = frozenset({WorkflowKind.MUNICIPAL_LIEN_SEARCH})
    scope = JurisdictionScope(country="US", state="FL")

    def __init__(self, *, directory: FloridaDirectory | None = None) -> None:
        self._directory = directory or load_directory()

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        """Florida places in the directory; a town that isn't gets the general plan."""
        if not self.scope.matches(jurisdiction):
            return False
        if self._directory.county(jurisdiction.county) is None:
            return False
        city = jurisdiction.municipality
        return (
            not city
            or is_unincorporated(city)
            or (self._directory.municipality(city, jurisdiction.county) is not None)
        )

    async def plan(self, request: WorkflowRequest) -> AdapterPlan:
        jurisdiction = request.jurisdiction
        county = self._directory.county(jurisdiction.county)
        city = jurisdiction.municipality
        municipality = (
            self._directory.municipality(city, jurisdiction.county)
            if city and not is_unincorporated(city)
            else None
        )
        office = municipality or county
        if office is None:
            raise LookupError(f"The Florida directory has no entry for {jurisdiction.key}.")
        steps = [_letter_step(office)]
        covers = set(office.lien_letter.covers) if _has_letter(office) else set()
        left_out = "The lien letter doesn't cover {}. " if _has_letter(office) else ""
        if LienCoverage.OPEN_PERMITS not in covers:
            steps.append(_permit_step(office, left_out.format("open permits")))
        if not _CODE <= covers:
            steps.append(_code_step(office, left_out.format("code cases")))
        if LienCoverage.UTILITIES not in covers:
            steps.append(_utility_step(office, left_out.format("utilities")))
        steps.append(_assessment_step(office))
        steps.append(
            WorkflowAction(
                label="Review the search results",
                description=(
                    "A reviewer reads the lien letter and the other results for open permits, "
                    "code liens, utility balances and assessments to be paid or cleared."
                ),
            )
        )
        requirements = [
            "Confirm the parcel's municipality on the property appraiser's record; the postal "
            "city isn't always the municipality.",
        ]
        if municipality is not None and county is not None:
            requirements.append(
                f"Check whether {county.name} provides any of the parcel's water, sewer or "
                "solid waste; its entry is in municipal_lien_directory."
            )
        return AdapterPlan(
            adapter_id=self.adapter_id,
            jurisdiction=jurisdiction,
            kind=request.kind,
            required_review=True,
            risk_level=RiskLevel.MEDIUM,
            steps=steps,
            external_requirements=requirements,
            routing_hints={
                "country": "US",
                "state": "FL",
                "county": county.name if county else "",
                "issuer": office.name,
                "channel": office.lien_letter.channel.value,
                "source": "municipal",
            },
        )


def _has_letter(office: MunicipalOffice) -> bool:
    letter = office.lien_letter
    return letter.offered is Offered.YES and letter.channel is not LienOrderChannel.NONE_FOUND


def _letter_step(office: MunicipalOffice) -> WorkflowAction:
    letter = office.lien_letter
    metadata = {
        "tool": "municipal_lien_directory",
        "channel": letter.channel.value,
        "request_url": letter.request_url,
        "vendor": letter.vendor,
        "fee_per_parcel": str(letter.fee_per_parcel) if letter.fee_per_parcel else None,
    }
    if not _has_letter(office):
        return WorkflowAction(
            label=f"Ask {office.name} for its lien information",
            description=(
                f"{office.name}'s pages don't describe a lien search letter. Ask its code "
                "enforcement, building and utility offices directly"
                + (f" ({office.website})." if office.website else ".")
            ),
            metadata={key: value for key, value in metadata.items() if value},
        )
    parts = [_how_to_order(office)]
    if letter.fee_per_parcel == 0:
        parts.append("There's no fee.")
    elif letter.fee_per_parcel is not None:
        parts.append(f"The fee is ${letter.fee_per_parcel:,.2f} a parcel.")
    elif letter.fee_text:
        parts.append(f"Fee: {letter.fee_text}")
    if letter.turnaround:
        parts.append(f"Turnaround: {letter.turnaround.rstrip('.')}.")
    if letter.covers:
        parts.append(
            "It covers " + ", ".join(c.value.replace("_", " ") for c in letter.covers) + "."
        )
    return WorkflowAction(
        label=f"Order {office.name}'s lien letter",
        description=" ".join(parts),
        metadata={key: value for key, value in metadata.items() if value},
    )


def _how_to_order(office: MunicipalOffice) -> str:
    letter = office.lien_letter
    issuer = f"Issuer: {(letter.issuer or office.name).rstrip('.')}."
    page = next(
        (
            url
            for url in (letter.request_url, letter.source_url, office.website)
            if url and not url.startswith("mailto:")
        ),
        None,
    )
    at = f" at {page}" if page else ""
    see = f"; it's described at {page}." if page else "."
    vendor = f" through {letter.vendor}" if letter.vendor else ""
    match letter.channel:
        case LienOrderChannel.ONLINE_PORTAL:
            return f"{issuer} Order it online{vendor}{at}."
        case LienOrderChannel.RECORDS_PORTAL:
            return f"{issuer} Request it as a public records request{vendor}{at}."
        case LienOrderChannel.EMAIL | LienOrderChannel.FORM_EMAIL:
            to = f" to {letter.request_email}" if letter.request_email else ""
            form = (
                "the request form" if letter.channel is LienOrderChannel.FORM_EMAIL else "a request"
            )
            return f"{issuer} Email {form}{to}{see}"
        case LienOrderChannel.MAIL:
            return f"{issuer} Mail the request{see}"
        case LienOrderChannel.FAX:
            return f"{issuer} Fax the request{see}"
    return f"{issuer} Ask {office.name} how to order it{see}"


def _permit_step(office: MunicipalOffice, left_out: str) -> WorkflowAction:
    permits = office.permits
    if permits.url:
        searched_by = (
            f" by {', '.join(by.replace('_', ' ') for by in permits.search_by)}"
            if permits.search_by
            else ""
        )
        description = f"{left_out}Search {office.name}'s permits{searched_by} at {permits.url}."
    else:
        description = f"{left_out}Ask {office.name}'s building department about open permits."
    return WorkflowAction(
        label="Check open and expired permits",
        description=description,
        metadata=(
            {"platform": permits.platform.value, "platform_name": permits.platform_name}
            if permits.url
            else {}
        ),
    )


def _code_step(office: MunicipalOffice, left_out: str) -> WorkflowAction:
    code = office.code_enforcement
    if code.public_search is Offered.YES and code.url:
        description = f"{left_out}Search {office.name}'s code cases at {code.url}."
    else:
        description = (
            f"{left_out}Ask {office.name}'s code enforcement office about open cases and "
            "code liens."
        )
    return WorkflowAction(label="Check code cases and code liens", description=description)


def _utility_step(office: MunicipalOffice, left_out: str) -> WorkflowAction:
    utilities = office.utilities
    provider = f"Water and sewer: {utilities.water_sewer}. " if utilities.water_sewer else ""
    match utilities.balance_request:
        case BalanceRequest.SEPARATE_REQUEST:
            ask = "Request the balance separately" + (
                f" at {utilities.balance_request_url}." if utilities.balance_request_url else "."
            )
        case BalanceRequest.NOT_OFFERED:
            ask = (
                "The provider doesn't give balances to title agents; ask the seller for a "
                "final bill."
            )
        case _:
            ask = "Ask the provider for the balance and a final reading."
    return WorkflowAction(
        label="Check utility balances",
        description=f"{left_out}{provider}{ask}",
    )


def _assessment_step(office: MunicipalOffice) -> WorkflowAction:
    assessments = office.special_assessments
    match assessments.billing:
        case AssessmentBilling.TAX_BILL:
            description = (
                "Special assessments are billed on the county tax bill as non-ad valorem "
                "assessments; read them on the tax bill."
            )
        case AssessmentBilling.DIRECT | AssessmentBilling.BOTH:
            description = (
                "Some special assessments are billed directly"
                + (f"; ask {assessments.office}." if assessments.office else ".")
                + " Others may be on the county tax bill."
            )
        case _:
            description = (
                "Read the county tax bill's non-ad valorem assessments, and ask "
                f"{office.name} about any assessment it bills directly."
            )
    return WorkflowAction(label="Check special assessments", description=description)

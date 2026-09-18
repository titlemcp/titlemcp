from __future__ import annotations

from title_mcp.domain.commitment import ClauseSet, ClauseTemplate, CommitmentSection

_B1 = CommitmentSection.SCHEDULE_B_I
_B2 = CommitmentSection.SCHEDULE_B_II


def _b1(clause_id: str, template: str) -> ClauseTemplate:
    return ClauseTemplate(clause_id=clause_id, section=_B1, template=template)


def _b2(clause_id: str, template: str) -> ClauseTemplate:
    return ClauseTemplate(clause_id=clause_id, section=_B2, template=template)


_STANDARD_B1 = [
    # Ordered as the 2021 ALTA Commitment form prints them. The first four are
    # supplied by the form itself; see ohio_default_clause_set().
    _b1(
        "b1.notify_additional_parties",
        "The Proposed Insured must notify the Company in writing of the name of any "
        "party not referred to in this Commitment who will obtain an interest in the "
        "Land or who will make a loan on the Land. The Company may then make "
        "additional Requirements or Exceptions.",
    ),
    _b1("b1.pay_consideration", "Pay the agreed amount for the estate or interest to be insured."),
    _b1("b1.pay_premiums", "Pay the premiums, fees, and charges for the Policy to the Company."),
    _b1(
        "b1.conveyance_documents",
        "Documents satisfactory to the Company that convey the Title or create the "
        "Mortgage to be insured, or both, must be properly authorized, executed, "
        "delivered, and recorded in the Public Records.",
    ),
    _b1(
        "b1.policy_amount",
        "The Proposed Policy Amount(s) must be modified to the full value of the estate "
        "or interest being insured, and any additional premium must be paid. The "
        "Proposed Policy Amount for an owner's policy should reflect the contract sales "
        "price unless the Company is furnished with a current appraisal indicating a "
        "different value. The Proposed Policy Amount for a loan policy will not be "
        "issued for an amount less than the principal amount of the mortgage debt or no "
        "more than 20% in excess of the principal debt in order to cover interest, "
        "foreclosure costs, etc. Proposed Policy Amount(s) will be revised, and premiums "
        "will be charged per the Company's Rate Manual then in effect when the final "
        "amounts of insurance are approved.",
    ),
    _b1(
        "b1.owners_sellers_affidavit",
        "Owners/Sellers Affidavit covering matters of title in a form acceptable to the Company.",
    ),
    _b1(
        "b1.further_exceptions",
        "Further exceptions and/or requirements may be made upon review of the proposed "
        "documents and/or upon further ascertaining the details of the transaction.",
    ),
    _b1(
        "b1.pay_taxes",
        "Pay all taxes, charges and assessments levied against subject premises, which "
        "are due and payable.",
    ),
    _b1(
        "b1.mechanics_lien_evidence",
        "Satisfactory evidence should be had that improvements and/or repairs or "
        "alterations thereto are completed; that contractor, sub-contractors, labor and "
        "materialmen are all paid; and have released of record all liens or notice of "
        "intent to perfect a lien for labor or material.",
    ),
]

_STANDARD_B2 = [
    _b2(
        "b2.gap",
        "Any defect, lien, encumbrance, adverse claim, or other matter that appears for "
        "the first time in the Public Records or is created, attaches, or is disclosed "
        "between the Commitment Date and the date on which all of the Schedule B, "
        "Part I – Requirements are met.",
    ),
    _b2(
        "b2.parties_in_possession",
        "Rights or claims of parties in possession not shown by the public records.",
    ),
    _b2(
        "b2.public_roadway_access",
        "Rights of others to access any public roadway lying within the boundary of the "
        "property described in Schedule A.",
    ),
    _b2(
        "b2.unrecorded_easements",
        "Easements, or claims of easements, not shown by the public records.",
    ),
    _b2(
        "b2.survey_matters",
        "Any encroachment, encumbrance, violation, variation, or adverse circumstance "
        "affecting the Title that would be disclosed by an accurate and complete land "
        "survey of the Land.",
    ),
    _b2(
        "b2.mechanics_liens",
        "Any lien, or right to a lien, for services, labor, or material heretofore or "
        "hereafter furnished, imposed by law and not shown by the public records.",
    ),
    _b2(
        "b2.unrecorded_taxes",
        "Taxes or special assessments which are not shown as existing liens by the public records.",
    ),
    _b2(
        "b2.minerals",
        "Any lease, grant, exception or reservation of minerals or mineral rights "
        "together with any rights appurtenant thereto.",
    ),
    _b2(
        "b2.orc_1529_31",
        "Pursuant to O.R.C. Section 1529.31(D), the following exception will appear on "
        "any loan policy: Oil and gas leases, pipeline agreements or any other "
        "instruments related to the production or sale of oil and gas which may arise "
        "subsequent to the date of the Policy.",
    ),
    _b2(
        "b2.retroactive_revaluation",
        "No liability is assumed for tax increases occasioned by retroactive revaluation "
        "arising out of the change in land usage, on account of errors or omissions and "
        "changes in the valuation of the property by legally constituted authorities.",
    ),
    _b2(
        "b2.area_not_insured",
        "Accuracy of the area or content of the land described herein is not insured.",
    ),
]


_DEED_REQUIREMENT = _b1(
    "b1.deed",
    "Deed from {sellers}, to {buyers}, with contractual rights under a purchase "
    "agreement(s) with the vested owner, conveying the property described herein in "
    "fee simple, free and unencumbered.",
)

_NEW_MORTGAGE_REQUIREMENT = _b1(
    "b1.new_mortgage",
    "Mortgage from {mortgagors}, to {lender}, in the sum of ${amount}, pertaining to the "
    "premises described in Exhibit A hereof.",
)

_MORTGAGE_PAYOFF = _b1(
    "b1.mortgage_payoff",
    "Mortgage from {borrowers}, to {lender}, in the amount of ${amount}{dated_clause}, "
    "as {recorded}.",
)

_EASEMENT_EXCEPTION = _b2(
    "b2.easement",
    "Easement and Right of Way granted to {second_party}, from {first_party}{dated_clause}, "
    "{recorded}.",
)

_EXCEPTION_BY_KIND = {
    "restriction": _b2(
        "b2.restriction",
        "Covenants, conditions, restrictions, and reservations as set forth in {cited}.",
    ),
    "plat": _b2(
        "b2.plat",
        "Terms, conditions, easements, setback lines, and all other matters shown on the "
        "{instrument_name}, {recorded}.",
    ),
    "lease": _b2(
        "b2.lease",
        "Terms and conditions of the lease from {first_party} to {second_party}"
        "{dated_clause}, {recorded}.",
    ),
    "agreement": _b2(
        "b2.agreement",
        "Terms and conditions of the agreement between {first_party} and {second_party}"
        "{dated_clause}, {recorded}.",
    ),
}

_GRANTEE_EASEMENT_EXCEPTION = _b2(
    "b2.easement_to_grantee",
    "Easement granted to {second_party}{dated_clause}, {recorded}.",
)

_UNRECORDED_EXCEPTION = _b2(
    "b2.unrecorded_instrument",
    "Terms, conditions, and all other matters set forth in the unrecorded {instrument_name}.",
)

_INSTRUMENT_EXCEPTION = _b2(
    "b2.recorded_instrument",
    "Terms, conditions, and all other matters set forth in the {instrument_name}, {recorded}.",
)

_JUDGMENT_RELEASE = _b1(
    "b1.judgment_release",
    "Release of record of the judgment in favor of {creditor}, against {debtor}"
    "{court_clause}{case_clause}{amount_clause}{recording_clause}.",
)

_TAX_EXCEPTION = _b2(
    "b2.tax",
    "The {county} County Treasurer's {tax_year} General Tax Duplicate shows:\n\n"
    "Taxes for the 1st half of {tax_year},{taxpayer_clause} in the amount of "
    "${first_half_amount} are {first_half_status}.  Taxes for the 2nd "
    "half {tax_year}, in the amount of ${second_half_amount} are "
    "{second_half_status}.\n"
    "{special_assessment_line}\n"
    "Taxes for the year {next_tax_year} are a lien but not yet determined, due or "
    "payable.\n\n"
    "Tax Parcel No.: {parcel_id}.\n\n"
    "County taxes are due and payable semi-annually beginning on or about February 1 "
    "and July 1{assessment_due_clause}.",
)


def ohio_default_clause_set() -> ClauseSet:
    """House wording for an Ohio commitment, as transcribed from the agency's own form.

    Clause order follows the 2021 ALTA Commitment form, and the clauses that form
    prints itself are listed in ``form_supplied_clause_ids`` so a renderer writing
    into it lines up without a hand-maintained skip list.

    This is a sample set that ships with the core package so the render service is
    runnable and testable on its own. Production clause sets belong in an agency
    package, where wording can be versioned per underwriter and per county.
    """

    return ClauseSet(
        clause_set_id="us-oh-default-v1",
        description="Ohio residential commitment, agency house wording (sample).",
        standard_b1=list(_STANDARD_B1),
        standard_b2=list(_STANDARD_B2),
        mortgage_payoff=_MORTGAGE_PAYOFF,
        tax_exception=_TAX_EXCEPTION,
        easement_exception=_EASEMENT_EXCEPTION,
        exception_by_kind=dict(_EXCEPTION_BY_KIND),
        instrument_exception=_INSTRUMENT_EXCEPTION,
        grantee_easement_exception=_GRANTEE_EASEMENT_EXCEPTION,
        unrecorded_exception=_UNRECORDED_EXCEPTION,
        judgment_requirement=_JUDGMENT_RELEASE,
        judgment_header="Release of the following judgment liens:",
        deed_requirement=_DEED_REQUIREMENT,
        mortgage_requirement=_NEW_MORTGAGE_REQUIREMENT,
        form_supplied_clause_ids=[
            "b1.notify_additional_parties",
            "b1.pay_consideration",
            "b1.pay_premiums",
            "b1.conveyance_documents",
            "b2.gap",
        ],
    )

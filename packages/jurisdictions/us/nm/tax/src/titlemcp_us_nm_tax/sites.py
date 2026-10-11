from __future__ import annotations

from titlemcp_platform_iasworld import AuditorSearchMode, IasWorldSiteConfig, TaxDueDate, TaxPage

# New Mexico county tax sites on Tyler iasWorld. Each answers
# property_tax_status_search; adding a county is an entry here.

# Bernalillo's Treasurer site serves one "realprop" search form for parcel,
# address and owner, with Lake County, Ohio's field names. Tax is on the
# "Balance Due" tab. The county's page gives the due dates: November 10 and
# April 10 of the next year, each delinquent 30 days later.
BERNALILLO = IasWorldSiteConfig(
    source_id="us-nm-bernalillo-tax",
    county="Bernalillo County",
    state="NM",
    name="Bernalillo County Treasurer Property Search",
    base_url="https://treasurer.bernco.gov/public.access/",
    district_code="000",
    owner="Bernalillo County Treasurer",
    priority=230,
    mode_map={mode: "realprop" for mode in AuditorSearchMode},
    form_field_overrides={"inpNumber": "inpNo", "inpOwner": "inpOwner1"},
    tax_page=TaxPage.BALANCE_DUE,
    tax_due_dates=[
        TaxDueDate(label="1st half", month=11, day=10),
        TaxDueDate(label="2nd half", month=4, day=10, years_after_tax_year=1),
    ],
    tax_notes=[
        "The county's page says each half becomes delinquent 30 days after it is due, "
        "on December 10 and May 10.",
    ],
)

NM_TAX_SITES: tuple[IasWorldSiteConfig, ...] = (BERNALILLO,)

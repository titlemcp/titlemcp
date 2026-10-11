from __future__ import annotations

from titlemcp_platform_iasworld import IasWorldSiteConfig, TaxDueDate, TaxPage

# Illinois county tax sites on Tyler iasWorld. Each answers
# property_tax_status_search; adding a county is an entry here.

# DuPage's property lookup, behind a click-through disclaimer. Taxes Billed is on
# the "Tax Summary" tab, each payment on "Tax Payment History", and sold or
# forfeited taxes on "Tax Redemption" and "Tax Status". Illinois taxes are paid
# the year after the tax year; an installment is delinquent after the later of
# June 1 (September 1 for the second) and the due date on the bill
# (35 ILCS 200/21-15).
DUPAGE = IasWorldSiteConfig(
    source_id="us-il-dupage-tax",
    county="DuPage County",
    state="IL",
    name="DuPage County Property Tax Information",
    base_url="https://propertylookup.dupagecounty.gov/",
    district_code="022",
    owner="DuPage County Treasurer",
    priority=230,
    tax_page=TaxPage.BILLED_AND_PAYMENTS,
    tax_due_dates=[
        TaxDueDate(label="1st installment", month=6, day=1, years_after_tax_year=1),
        TaxDueDate(label="2nd installment", month=9, day=1, years_after_tax_year=1),
    ],
    tax_notes=[
        "Installments are taken as due June 1 and September 1 of the year after the tax "
        "year, the earliest Illinois allows; the bill can set later dates (35 ILCS "
        "200/21-15).",
    ],
)

IL_TAX_SITES: tuple[IasWorldSiteConfig, ...] = (DUPAGE,)

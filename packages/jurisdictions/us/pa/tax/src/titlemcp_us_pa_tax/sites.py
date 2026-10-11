from __future__ import annotations

from titlemcp_platform_iasworld import IasWorldSiteConfig, TaxDueDate, TaxPage

# Pennsylvania county tax sites on Tyler iasWorld. Each answers
# property_tax_status_search; adding a county is an entry here.

# Delaware County's Real Estate and Tax Records site, behind a click-through
# disclaimer. The parcel's page has the County Tax Receivable and Delinquent Tax
# tables. County bills are mailed February 1: a 2% discount for two months, the
# face amount for the next two, then a 10% penalty, so a bill is due four months
# after its billing date. School district and municipal taxes are billed locally
# and aren't on this site.
DELAWARE = IasWorldSiteConfig(
    source_id="us-pa-delaware-tax",
    county="Delaware County",
    state="PA",
    name="Delaware County Real Estate and Tax Records",
    base_url="http://delcorealestate.co.delaware.pa.us/pt/",
    district_code="000",
    owner="Delaware County Treasurer",
    priority=230,
    tax_page=TaxPage.COUNTY_RECEIVABLE,
    tax_due_months_after_billing=4,
    tax_due_dates=[TaxDueDate(label="County tax", month=6, day=1)],
    tax_notes=[
        (
            "The county's site shows county real estate tax only. School district and "
            "municipal real estate taxes are billed and collected locally."
        ),
        "Unpaid county tax goes to the Tax Claim Bureau after the year ends.",
    ],
)

PA_TAX_SITES: tuple[IasWorldSiteConfig, ...] = (DELAWARE,)

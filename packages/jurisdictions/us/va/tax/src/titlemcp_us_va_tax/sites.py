from __future__ import annotations

from titlemcp_platform_iasworld import IasWorldSiteConfig, TaxDueDate, TaxPage

# Virginia county tax sites on Tyler iasWorld. Each answers
# property_tax_status_search; adding a county is an entry here.

# Fairfax's iCARE site, run by the Department of Tax Administration. Tax is on
# the "Tax Details" tab, one row per half. The county publishes due dates of
# July 28 and December 5, moved to the next business day when they fall on a
# weekend or holiday.
FAIRFAX = IasWorldSiteConfig(
    source_id="us-va-fairfax-tax",
    county="Fairfax County",
    state="VA",
    name="Fairfax County Department of Tax Administration iCARE",
    base_url="https://icare.fairfaxcounty.gov/ffxcare/",
    district_code="129",
    numeric_parcel_ids=False,
    owner="Fairfax County Department of Tax Administration",
    priority=230,
    tax_page=TaxPage.CURRENT_YEAR_SUMMARY,
    tax_due_dates=[
        TaxDueDate(label="1st half", month=7, day=28),
        TaxDueDate(label="2nd half", month=12, day=5),
    ],
    tax_notes=[
        (
            "The county's iCARE page summarizes the current year's real estate tax; it "
            "doesn't list earlier years."
        ),
        "The towns of Herndon, Vienna and Clifton bill their own real estate tax.",
    ],
)

VA_TAX_SITES: tuple[IasWorldSiteConfig, ...] = (FAIRFAX,)

from __future__ import annotations

from titlemcp_platform_publicsearch import PublicSearchSiteConfig

# Colorado county clerks and recorders on Kofile PublicSearch. A deed of trust
# secures the loan, and the public trustee records its release.
# Adding a county on a supported platform is a config entry here.

ARAPAHOE = PublicSearchSiteConfig(
    source_id="us-co-arapahoe-recorder",
    county="Arapahoe County",
    state="CO",
    name="Arapahoe County, Colorado Clerk and Recorder",
    base_url="https://arapahoe.co.publicsearch.us",
    owner="Arapahoe County Clerk and Recorder",
)

#: Every Colorado county with a recorder connector.
CO_RECORDER_SITES: tuple[PublicSearchSiteConfig, ...] = (ARAPAHOE,)

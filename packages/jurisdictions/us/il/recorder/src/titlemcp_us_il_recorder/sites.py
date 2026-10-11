from __future__ import annotations

from titlemcp_platform_publicsearch import PublicSearchSiteConfig

# Illinois county recorders on Kofile PublicSearch.
# Adding a county on a supported platform is a config entry here.

LAKE = PublicSearchSiteConfig(
    source_id="us-il-lake-recorder",
    county="Lake County",
    state="IL",
    name="Lake County, Illinois County Clerk",
    base_url="https://lake.il.publicsearch.us",
    owner="Lake County Clerk",
)

#: Every Illinois county with a recorder connector.
IL_RECORDER_SITES: tuple[PublicSearchSiteConfig, ...] = (LAKE,)

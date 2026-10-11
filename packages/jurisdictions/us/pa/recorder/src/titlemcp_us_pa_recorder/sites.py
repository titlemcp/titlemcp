from __future__ import annotations

from titlemcp_platform_publicsearch import PublicSearchSiteConfig

# Pennsylvania recorders of deeds on Kofile PublicSearch.
# Adding a county on a supported platform is a config entry here.

DELAWARE = PublicSearchSiteConfig(
    source_id="us-pa-delaware-recorder",
    county="Delaware County",
    state="PA",
    name="Delaware County, Pennsylvania Recorder of Deeds",
    base_url="https://delaware.pa.publicsearch.us",
    owner="Delaware County Recorder of Deeds",
)

#: Every Pennsylvania county with a recorder connector.
PA_RECORDER_SITES: tuple[PublicSearchSiteConfig, ...] = (DELAWARE,)

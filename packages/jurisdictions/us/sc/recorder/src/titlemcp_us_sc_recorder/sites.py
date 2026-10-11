from __future__ import annotations

from titlemcp_platform_publicsearch import PublicSearchSiteConfig

# South Carolina registers of deeds on Kofile PublicSearch.
# Adding a county on a supported platform is a config entry here.

GREENVILLE = PublicSearchSiteConfig(
    source_id="us-sc-greenville-recorder",
    county="Greenville County",
    state="SC",
    name="Greenville County, South Carolina Register of Deeds",
    base_url="https://greenville.sc.publicsearch.us",
    owner="Greenville County Register of Deeds",
)

#: Every South Carolina county with a recorder connector.
SC_RECORDER_SITES: tuple[PublicSearchSiteConfig, ...] = (GREENVILLE,)

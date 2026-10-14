from __future__ import annotations

from titlemcp_platform_countyfusion import CountyFusionSiteConfig
from titlemcp_platform_publicsearch import PublicSearchSiteConfig

from title_mcp.domain.recorder import InstrumentKind

# Ohio county recorders, by the platform their public index runs on. Adding a
# county on a supported platform is a config entry here; the protocol and the
# release lookup live in the platform packages and in title_mcp.
#
# Franklin runs PublicSearch too, and has its own package
# (titlemcp-us-oh-franklin-recorder) for assembling a parcel's chain.

CUYAHOGA = PublicSearchSiteConfig(
    source_id="us-oh-cuyahoga-recorder",
    county="Cuyahoga County",
    state="OH",
    name="Cuyahoga County, Ohio Recorder",
    base_url="https://cuyahoga.oh.publicsearch.us",
    owner="Cuyahoga County Fiscal Officer, Recording",
)

STARK = PublicSearchSiteConfig(
    source_id="us-oh-stark-recorder",
    county="Stark County",
    state="OH",
    name="Stark County, Ohio Recorder",
    base_url="https://stark.oh.publicsearch.us",
    owner="Stark County Recorder",
)

OH_PUBLICSEARCH_SITES: tuple[PublicSearchSiteConfig, ...] = (CUYAHOGA, STARK)

# Wayne's own website doesn't link its index; countyfusion7, countyfusion8 and
# a govos.com host all serve it. The county key picks the county on a shared host.
WAYNE = CountyFusionSiteConfig(
    source_id="us-oh-wayne-recorder",
    county="Wayne County",
    state="OH",
    name="Wayne County, Ohio Recorder",
    host="countyfusion8.kofiletech.us",
    county_key="WayneOH",
    owner="Wayne County Recorder",
)

ASHLAND = CountyFusionSiteConfig(
    source_id="us-oh-ashland-recorder",
    county="Ashland County",
    state="OH",
    name="Ashland County, Ohio Recorder",
    host="countyfusion10.kofiletech.us",
    county_key="AshlandOH",
    owner="Ashland County Recorder",
)

SENECA = CountyFusionSiteConfig(
    source_id="us-oh-seneca-recorder",
    county="Seneca County",
    state="OH",
    name="Seneca County, Ohio Recorder",
    host="countyfusion13.kofiletech.us",
    county_key="SenecaOH",
    owner="Seneca County Recorder",
    # Seneca indexes some releases as SPECIAL RELEASE without saying what makes
    # them special. Read as partial, a reviewer looks at one before it counts.
    document_type_kinds={"SPECIAL RELEASE": InstrumentKind.PARTIAL_RELEASE},
)

# Tuscarawas and Richland offer "Login as Guest" rather than "Login as Public".
# A guest's result list doesn't flag documents with links, so each document's
# detail is read for them.
TUSCARAWAS = CountyFusionSiteConfig(
    source_id="us-oh-tuscarawas-recorder",
    county="Tuscarawas County",
    state="OH",
    name="Tuscarawas County, Ohio Recorder",
    host="countyfusion10.kofiletech.us",
    county_key="TuscarawasOH",
    owner="Tuscarawas County Recorder",
    guest_login=True,
)

RICHLAND = CountyFusionSiteConfig(
    source_id="us-oh-richland-recorder",
    county="Richland County",
    state="OH",
    name="Richland County, Ohio Recorder",
    host="countyfusion13.kofiletech.us",
    county_key="RichlandOH",
    owner="Richland County Recorder",
    guest_login=True,
)

OH_COUNTYFUSION_SITES: tuple[CountyFusionSiteConfig, ...] = (
    WAYNE,
    ASHLAND,
    SENECA,
    TUSCARAWAS,
    RICHLAND,
)

#: Every Ohio county with a recorder connector, whatever its platform.
OH_RECORDER_SITES: tuple[PublicSearchSiteConfig | CountyFusionSiteConfig, ...] = (
    OH_PUBLICSEARCH_SITES + OH_COUNTYFUSION_SITES
)

from __future__ import annotations

from titlemcp_platform_publicsearch import PublicSearchSiteConfig

from title_mcp.domain.recorder import InstrumentKind

# Texas county clerks, all on Kofile PublicSearch. A deed of trust secures the
# loan here, and the core classifier reads it as the mortgage. Dallas, Denton,
# Hidalgo and Montgomery index a deed of trust's release as a plain RELEASE OF
# LIEN, which elsewhere means another lien's release, so they say so by type code.
# Adding a county on a supported platform is a config entry here.

DALLAS = PublicSearchSiteConfig(
    source_id="us-tx-dallas-recorder",
    county="Dallas County",
    state="TX",
    name="Dallas County, Texas County Clerk",
    base_url="https://dallas.tx.publicsearch.us",
    owner="Dallas County Clerk",
    document_type_kinds={"RE": InstrumentKind.RELEASE},
)

TARRANT = PublicSearchSiteConfig(
    source_id="us-tx-tarrant-recorder",
    county="Tarrant County",
    state="TX",
    name="Tarrant County, Texas County Clerk",
    base_url="https://tarrant.tx.publicsearch.us",
    owner="Tarrant County Clerk",
)

BEXAR = PublicSearchSiteConfig(
    source_id="us-tx-bexar-recorder",
    county="Bexar County",
    state="TX",
    name="Bexar County, Texas County Clerk",
    base_url="https://bexar.tx.publicsearch.us",
    owner="Bexar County Clerk",
)

COLLIN = PublicSearchSiteConfig(
    source_id="us-tx-collin-recorder",
    county="Collin County",
    state="TX",
    name="Collin County, Texas County Clerk",
    base_url="https://collin.tx.publicsearch.us",
    owner="Collin County Clerk",
)

DENTON = PublicSearchSiteConfig(
    source_id="us-tx-denton-recorder",
    county="Denton County",
    state="TX",
    name="Denton County, Texas County Clerk",
    base_url="https://denton.tx.publicsearch.us",
    owner="Denton County Clerk",
    document_type_kinds={"RE": InstrumentKind.RELEASE},
)

HIDALGO = PublicSearchSiteConfig(
    source_id="us-tx-hidalgo-recorder",
    county="Hidalgo County",
    state="TX",
    name="Hidalgo County, Texas County Clerk",
    base_url="https://hidalgo.tx.publicsearch.us",
    owner="Hidalgo County Clerk",
    document_type_kinds={
        "RELEASE OF LIEN": InstrumentKind.RELEASE,
        "P/REL OF LIEN": InstrumentKind.PARTIAL_RELEASE,
    },
)

MONTGOMERY = PublicSearchSiteConfig(
    source_id="us-tx-montgomery-recorder",
    county="Montgomery County",
    state="TX",
    name="Montgomery County, Texas County Clerk",
    base_url="https://montgomery.tx.publicsearch.us",
    owner="Montgomery County Clerk",
    document_type_kinds={"RLN": InstrumentKind.RELEASE},
)

#: Every Texas county with a recorder connector.
TX_RECORDER_SITES: tuple[PublicSearchSiteConfig, ...] = (
    DALLAS,
    TARRANT,
    BEXAR,
    COLLIN,
    DENTON,
    HIDALGO,
    MONTGOMERY,
)

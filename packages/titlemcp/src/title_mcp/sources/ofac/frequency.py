"""How common a name token is in the United States, as a weight for matching."""

from __future__ import annotations

import gzip
import math
from functools import cache
from pathlib import Path

from title_mcp.sources.ofac.normalize import (
    COMMON_GLOBAL_GIVEN_NAMES,
    GENERIC_ENTITY_WORDS,
    PARTICLES,
)

TABLE = Path(__file__).with_name("data") / "us_name_frequency.tsv.gz"

#: Weight of a token no one carries (or that the table leaves out): fully telling.
RARE = 1.0
#: Lowest weight any real name token gets, however common.
FLOOR = 0.12


@cache
def table() -> dict[str, float]:
    """Token -> people per 100,000 (U.S. Census; see scripts/build_ofac_name_frequency.py)."""

    if not TABLE.exists():
        return {}
    found: dict[str, float] = {}
    with gzip.open(TABLE, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            name, _, per = line.rstrip("\n").partition("\t")
            if name and per:
                found[name] = float(per)
    return found


def weight(token: str, *, entity: bool = False) -> float:
    """How much a token says about identity, 0 to 1.

    SMITH (828 per 100,000) weighs about 0.42, GARCIA 0.48, KHAN 0.73, and a name
    absent from the table 1.0. Particles weigh 0.15; generic company words 0.2.
    """

    if token in PARTICLES:
        return 0.15
    if entity and token in GENERIC_ENTITY_WORDS:
        return 0.2
    if len(token) == 1:
        return 0.3
    if token in COMMON_GLOBAL_GIVEN_NAMES:
        return 0.4
    per = table().get(token)
    if not per:
        # A short initialism (MMT, RJB) identifies little: many companies share one.
        return 0.5 if entity and len(token) <= 3 else RARE
    # log scale: 1 per 100,000 -> 1.0; 10 -> 0.8; 100 -> 0.6; 1,000 -> 0.4
    return max(FLOOR, min(RARE, 1.0 - 0.2 * math.log10(max(per, 1.0))))

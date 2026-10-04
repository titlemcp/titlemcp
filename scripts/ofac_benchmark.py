"""Benchmark OFAC screening: what it catches, and how many innocent names it flags.

    python scripts/ofac_benchmark.py <SDN.XML> <Names_2010Census.csv> <dist.male.first> \
        <dist.female.first> [--sample 400] [--seed 7]

Positives are real SDN individuals and entities whose names are disguised the ways
names arrive on real files: a transliteration swap, a typo, "LAST, FIRST" order, a
dropped middle name, a first initial, a different company suffix. A positive counts as
caught when its own listing comes back (as a potential match, or at all).

Negatives are realistic U.S. people (Census first names and surnames drawn by real
frequency) and U.S.-style company names that are not on the list. Any flag on them
is a false alarm.

The baseline is the common approach: the whole normalized name compared by
Jaro-Winkler against every listed name and alias (weak aliases included) at a single
threshold. It is reported at several thresholds, so the engine can be compared at the
same catch rate.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/titlemcp/src"))

from title_mcp.sources.ofac import phonetic  # noqa: E402
from title_mcp.sources.ofac.lists import parse  # noqa: E402
from title_mcp.sources.ofac.match import Screener  # noqa: E402
from title_mcp.sources.ofac.models import (  # noqa: E402
    EntryType,
    Outcome,
    PartyType,
    SanctionsList,
    ScreeningParty,
)
from title_mcp.sources.ofac.normalize import VARIANTS, fold, tokens  # noqa: E402

COMPANY_WORDS = (
    "Holdings Properties Realty Investments Capital Partners Group Development Homes "
    "Construction Management Ventures Enterprises Trading Global Services Land Title "
    "Mortgage Builders Associates Acquisitions Equity Rentals"
).split()
PLACES = (
    "Riverside Oakwood Lakeview Maple Summit Pine Valley Cedar Harbor Meadow Hillcrest "
    "Brookside Highland Fairview Westfield Northgate Eastwood Sunset Parkside Willow"
).split()
SUFFIXES = ["LLC", "Inc", "LLC", "Corp", "LP", "Co", "Ltd"]

_REVERSE: dict[str, list[str]] = {}
for spelling, canonical in VARIANTS.items():
    _REVERSE.setdefault(canonical, []).append(spelling)


def _weighted(path: Path, *, census_2010: bool) -> tuple[list[str], list[float]]:
    names, weights = [], []
    if census_2010:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    weights.append(float(row["prop100k"]))
                except ValueError:
                    continue
                names.append(row["name"].title())
    else:
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                names.append(parts[0].title())
                weights.append(float(parts[1]))
    return names, weights


def disguise(name: str, entry_type: EntryType, rng: random.Random) -> tuple[str, str]:
    """A plausibly mis-entered version of a listed name, and what was done to it."""

    words = fold(name).split()
    if not words:
        return name, "unchanged"
    kinds = ["typo", "case"]
    if entry_type is EntryType.INDIVIDUAL and len(words) >= 2:
        kinds += ["reorder"]  # files write people LAST, FIRST; companies are not reordered
    if entry_type is EntryType.INDIVIDUAL and len(words) >= 3:
        kinds += ["drop_middle"]
    if entry_type is EntryType.INDIVIDUAL and len(words) >= 2:
        kinds += ["initial"]
    if any(w in _REVERSE or VARIANTS.get(w) in _REVERSE for w in words):
        kinds += ["transliterate"] * 3
    if entry_type is EntryType.ENTITY:
        kinds += ["suffix"]
    kind = rng.choice(kinds)
    if kind == "typo":
        candidates = [i for i, w in enumerate(words) if len(w) >= 5]
        if not candidates:
            return name.lower(), "case"
        i = rng.choice(candidates)
        w = words[i]
        j = rng.randrange(1, len(w) - 1)
        words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]  # swap two letters
    elif kind == "reorder":
        words = [words[-1] + ","] + words[:-1]
    elif kind == "drop_middle":
        words = [words[0], words[-1]]
    elif kind == "initial":
        words = [words[0][0] + "."] + words[1:]
    elif kind == "transliterate":
        for i, w in enumerate(words):
            canonical = VARIANTS.get(w, w)
            options = [s for s in _REVERSE.get(canonical, []) if s != w]
            if options:
                words[i] = rng.choice(options)
                break
    elif kind == "suffix":
        words = [w for w in words if w not in {"LLC", "LTD", "LIMITED", "INC", "CO", "CORP"}]
        words.append(rng.choice(SUFFIXES))
    elif kind == "case":
        return name.lower(), kind
    return " ".join(words), kind


_SCREENER: Screener | None = None
_FORMS: list[tuple[str, str]] = []


def _init_worker(sdn_path: str) -> None:
    """Each worker process loads the list and builds its own index once."""

    global _SCREENER, _FORMS
    entries, _, _ = parse(Path(sdn_path).read_bytes(), SanctionsList.SDN)
    _SCREENER = Screener(entries)
    _FORMS = [
        (e.uid, " ".join(tokens(n.full_name, entity=e.entry_type is not EntryType.INDIVIDUAL)))
        for e in entries
        for n in e.names
    ]


def _screen_one(item: tuple[str, str]) -> tuple[str, dict[str, str]]:
    name, party_type = item
    assert _SCREENER is not None
    found = _SCREENER.screen(ScreeningParty(name=name, party_type=PartyType(party_type)))
    return found.outcome.value, {c.uid: c.outcome.value for c in found.candidates}


def _baseline_one(item: tuple[str, str, float]) -> dict[str, float]:
    """Best whole-name score per listing at or above the lowest threshold.

    The name is normalized as the listings are (legal forms dropped for companies),
    so the baseline is judged on names, not on suffixes.
    """

    name, party_type, floor = item
    folded = " ".join(tokens(name, entity=party_type == PartyType.ENTITY.value))
    best: dict[str, float] = {}
    for uid, listed in _FORMS:
        score = phonetic.jaro_winkler(folded, listed)
        if score >= floor and score > best.get(uid, 0.0):
            best[uid] = score
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sdn")
    parser.add_argument("surnames")
    parser.add_argument("male")
    parser.add_argument("female")
    parser.add_argument("--sample", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--baseline-thresholds", default="0.85,0.88,0.90,0.92,0.95")
    parser.add_argument(
        "--no-baseline", action="store_true", help="Skip the (slow) whole-name baseline"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(16, (os.cpu_count() or 2) - 1)),
        help="Worker processes (matching is CPU-bound, so processes, not threads)",
    )
    args = parser.parse_args()
    rng = random.Random(args.seed)

    entries, publish_date, _ = parse(Path(args.sdn).read_bytes(), SanctionsList.SDN)
    forms = [
        (e.uid, " ".join(tokens(n.full_name, entity=e.entry_type is not EntryType.INDIVIDUAL)))
        for e in entries
        for n in e.names
    ]
    listed_names = {f for _, f in forms}

    people = [e for e in entries if e.entry_type is EntryType.INDIVIDUAL]
    companies = [e for e in entries if e.entry_type is EntryType.ENTITY]
    positives = []
    for pool, party_type in ((people, PartyType.INDIVIDUAL), (companies, PartyType.ENTITY)):
        for entry in rng.sample(pool, args.sample // 2):
            name, kind = disguise(entry.primary_name, entry.entry_type, rng)
            positives.append((entry.uid, name, kind, party_type))

    surnames, surname_weights = _weighted(Path(args.surnames), census_2010=True)
    first_names, first_weights = [], []
    for path in (args.male, args.female):
        names, weights = _weighted(Path(path), census_2010=False)
        first_names += names
        first_weights += weights
    negatives = []
    while len(negatives) < args.sample:
        if rng.random() < 0.7:
            first = rng.choices(first_names, first_weights)[0]
            last = rng.choices(surnames, surname_weights)[0]
            name, party_type = f"{first} {last}", PartyType.INDIVIDUAL
        else:
            lead = rng.choice([rng.choices(surnames, surname_weights)[0], rng.choice(PLACES)])
            words = rng.sample(COMPANY_WORDS, rng.choice([1, 1, 2]))
            name, party_type = f"{lead} {' '.join(words)} {rng.choice(SUFFIXES)}", PartyType.ENTITY
        if " ".join(tokens(name, entity=party_type is PartyType.ENTITY)) not in listed_names:
            negatives.append((name, party_type))

    print(f"SDN list published {publish_date}: {len(entries)} entries, {len(forms)} names")
    print(f"{len(positives)} disguised listed names, {len(negatives)} unlisted U.S. names\n")

    items = [(name, pt.value) for _, name, _, pt in positives]
    items += [(name, pt.value) for name, pt in negatives]
    started = time.time()
    with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(args.sdn,)) as pool:
        screened = list(pool.map(_screen_one, items, chunksize=8))
        took = time.time() - started
        caught_potential = caught_any = 0
        by_kind: dict[str, list[int]] = {}
        for (uid, _, kind, _), (_, uids) in zip(positives, screened[: len(positives)], strict=True):
            potential = uids.get(uid) == Outcome.POTENTIAL_MATCH.value
            caught_potential += potential
            caught_any += uid in uids
            by_kind.setdefault(kind, [0, 0])
            by_kind[kind][0] += potential
            by_kind[kind][1] += 1
        negative_outcomes = [outcome for outcome, _ in screened[len(positives) :]]
        flagged_potential = negative_outcomes.count(Outcome.POTENTIAL_MATCH.value)
        flagged_any = sum(o != Outcome.NO_MATCH.value for o in negative_outcomes)
        n_pos, n_neg = len(positives), len(negatives)
        print(f"This engine ({args.workers} worker processes)")
        print(f"  caught as potential match: {caught_potential / n_pos:6.1%}")
        print(f"  surfaced at all:           {caught_any / n_pos:6.1%}")
        print(f"  false alarms (potential):  {flagged_potential / n_neg:6.1%}")
        print(f"  shown as likely false pos: {(flagged_any - flagged_potential) / n_neg:6.1%}")
        print(f"  {len(items)} names in {took:.1f}s across {args.workers} processes")
        print(
            "  caught as potential, by disguise: "
            + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(by_kind.items()))
        )
        if args.no_baseline:
            return
        thresholds = [float(t) for t in args.baseline_thresholds.split(",")]
        started = time.time()
        best = list(
            pool.map(_baseline_one, [(n, pt, min(thresholds)) for n, pt in items], chunksize=4)
        )
        print(
            "\nBaseline: whole-name Jaro-Winkler against every name and alias "
            f"({time.time() - started:.0f}s)"
        )
        for threshold in thresholds:
            caught = sum(
                scores.get(uid, 0.0) >= threshold
                for (uid, _, _, _), scores in zip(positives, best[: len(positives)], strict=True)
            )
            flagged = sum(
                any(v >= threshold for v in scores.values()) for scores in best[len(positives) :]
            )
            print(
                f"  threshold {threshold:.2f}: caught {caught / n_pos:6.1%}, "
                f"false alarms {flagged / n_neg:6.1%}"
            )


if __name__ == "__main__":
    main()

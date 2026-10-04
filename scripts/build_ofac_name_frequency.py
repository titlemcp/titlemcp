"""Build the US name-frequency table the OFAC screener uses to weight name tokens.

    python scripts/build_ofac_name_frequency.py <Names_2010Census.csv> <dist.male.first> \
        <dist.female.first> [out.tsv.gz]

Inputs are U.S. Census Bureau public-domain files:

- 2010 surnames: https://www2.census.gov/topics/genealogy/2010surnames/names.zip
  (``name, rank, count, prop100k, ...``)
- 1990 first names: https://www2.census.gov/topics/genealogy/1990surnames/dist.male.first
  and dist.female.first (``NAME  percent  cumulative  rank``)

The output maps each name token to how many people per 100,000 carry it (the larger
of its surname and first-name frequencies). A common token ("SMITH", "JOHN") then
counts for less in a match than a rare one, which is most of what keeps common names
from raising false alarms.
"""

from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

#: Surnames rarer than this (people per 100,000) are left out: absent tokens are
#: treated as rare anyway, and the table stays small.
MIN_PER_100K = 0.35


def build(surnames: Path, male: Path, female: Path) -> dict[str, float]:
    table: dict[str, float] = {}
    with surnames.open(newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["name"].strip().upper()
            try:
                per = float(row["prop100k"])
            except ValueError:
                continue
            if name and name != "ALL OTHER NAMES" and per >= MIN_PER_100K:
                table[name] = max(table.get(name, 0.0), per)
    for path in (male, female):
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                # Percent of one sex: about half the population, so per 100,000 people.
                per = float(parts[1]) * 1000 / 2
                table[parts[0].upper()] = max(table.get(parts[0].upper(), 0.0), per)
    return table


def main(argv: list[str]) -> None:
    if len(argv) < 4:
        raise SystemExit(__doc__)
    default = (
        Path(__file__).parents[1]
        / "packages/titlemcp/src/title_mcp/sources/ofac/data/us_name_frequency.tsv.gz"
    )
    out = Path(argv[4]) if len(argv) > 4 else default
    table = build(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        handle.write("# token\tper_100k (U.S. Census 2010 surnames, 1990 first names)\n")
        for name, per in sorted(table.items(), key=lambda kv: -kv[1]):
            handle.write(f"{name}\t{per:.3f}\n")
    print(f"{len(table)} tokens -> {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv)

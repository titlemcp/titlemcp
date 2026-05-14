from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CENSUS_BASE_URL = "https://www2.census.gov/geo/docs/reference/codes/files"
COUNTY_URL = f"{CENSUS_BASE_URL}/national_county.txt"
PLACE_URL = f"{CENSUS_BASE_URL}/national_places.txt"
COUSUB_URL = f"{CENSUS_BASE_URL}/national_cousub.txt"

STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "AS": "American Samoa",
    "GU": "Guam",
    "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico",
    "UM": "U.S. Minor Outlying Islands",
    "VI": "U.S. Virgin Islands",
}


@dataclass(frozen=True)
class County:
    state: str
    state_fips: str
    county_fips: str
    name: str
    funcstat: str
    path: Path


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_") or "unnamed"


def name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(normalized.replace("-", " ").lower().split())


def download_text(url: str, timeout: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("latin1")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if path.name == "_jurisdiction.json":
        capabilities_path = path.parent / "capabilities"
        capabilities_path.mkdir(parents=True, exist_ok=True)
        (capabilities_path / ".gitkeep").touch()


def placeholder_payload(
    *,
    jurisdiction: dict[str, str | None],
    geography: dict[str, Any],
    relative_path: Path,
) -> dict[str, Any]:
    return {
        "jurisdiction": {key: value for key, value in jurisdiction.items() if value},
        "geography": geography,
        "capabilities": {
            "adapters": [],
            "tools": [],
            "workflows": [],
            "schemas": [],
        },
        "capability_convention": {
            "create_here": str(relative_path / "capabilities"),
            "template": "packages/titlemcp/templates/jurisdiction-package",
            "notes": (
                "Add jurisdiction-specific adapters, tools, workflows, schemas, or tests here. "
                "Keep shared logic in packages/titlemcp/src/title_mcp and call it from "
                "jurisdiction code."
            ),
        },
    }


def parse_counties(text: str, root: Path) -> tuple[list[County], dict[tuple[str, str], County]]:
    counties: list[County] = []
    by_state_and_name: dict[tuple[str, str], County] = {}
    for state, state_fips, county_fips, county_name, funcstat in csv.reader(io.StringIO(text)):
        county_path = (
            root
            / "US"
            / "states"
            / state
            / "counties"
            / f"{slugify(county_name)}__{state_fips}{county_fips}"
        )
        county = County(
            state=state,
            state_fips=state_fips,
            county_fips=county_fips,
            name=county_name,
            funcstat=funcstat,
            path=county_path,
        )
        counties.append(county)
        by_state_and_name[(state, name_key(county_name))] = county
    return counties, by_state_and_name


def write_root_files(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "# Jurisdiction Workspace\n\n"
        "Generated placeholders for country, state, county, municipality, and county-subdivision "
        "specific title-operation capabilities.\n\n"
        "Create new MCP capabilities in the relevant jurisdiction directory using the convention "
        "described in `_jurisdiction.json`. Regenerate this tree with:\n\n"
        "```bash\n"
        ".venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py "
        "--root jurisdiction-catalog --clean\n"
        "```\n",
        encoding="utf-8",
    )

    template_root = root / "_templates" / "capability_package"
    for directory in ["adapters", "tools", "workflows", "schemas", "tests"]:
        directory_path = template_root / directory
        directory_path.mkdir(parents=True, exist_ok=True)
        (directory_path / "README.md").write_text(
            f"# {directory.title()}\n\n"
            "Place jurisdiction-specific implementation files here when a capability needs "
            "behavior that differs from shared platform defaults.\n",
            encoding="utf-8",
        )

    write_json(
        root / "US" / "_jurisdiction.json",
        placeholder_payload(
            jurisdiction={"country": "US"},
            geography={"type": "country", "name": "United States"},
            relative_path=Path("jurisdiction-catalog/US"),
        ),
    )


def write_states_and_counties(root: Path, counties: list[County]) -> None:
    states = sorted({(county.state, county.state_fips) for county in counties})
    for state, state_fips in states:
        state_path = root / "US" / "states" / state
        write_json(
            state_path / "_jurisdiction.json",
            placeholder_payload(
                jurisdiction={"country": "US", "state": state},
                geography={
                    "type": "state",
                    "name": STATE_NAMES.get(state, state),
                    "state": state,
                    "state_fips": state_fips,
                    "source": COUNTY_URL,
                },
                relative_path=state_path,
            ),
        )

    for county in counties:
        write_json(
            county.path / "_jurisdiction.json",
            placeholder_payload(
                jurisdiction={
                    "country": "US",
                    "state": county.state,
                    "county": county.name,
                },
                geography={
                    "type": "county",
                    "name": county.name,
                    "state": county.state,
                    "state_fips": county.state_fips,
                    "county_fips": county.county_fips,
                    "funcstat": county.funcstat,
                    "source": COUNTY_URL,
                },
                relative_path=county.path,
            ),
        )


def split_county_names(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def write_municipalities(
    *,
    text: str,
    root: Path,
    counties_by_name: dict[tuple[str, str], County],
    include_cdps: bool,
) -> tuple[int, int]:
    written = 0
    unmatched = 0
    rows = csv.DictReader(io.StringIO(text), delimiter="|")
    for row in rows:
        place_type = row["TYPE"]
        if place_type != "Incorporated Place" and not include_cdps:
            continue

        for county_name in split_county_names(row["COUNTY"]):
            county = counties_by_name.get((row["STATE"], name_key(county_name)))
            if county is None:
                unmatched += 1
                continue

            place_name = row["PLACENAME"]
            place_path = (
                county.path
                / "municipalities"
                / f"{slugify(place_name)}__{row['STATEFP']}{row['PLACEFP']}"
            )
            write_json(
                place_path / "_jurisdiction.json",
                placeholder_payload(
                    jurisdiction={
                        "country": "US",
                        "state": row["STATE"],
                        "county": county.name,
                        "municipality": place_name,
                    },
                    geography={
                        "type": "municipality",
                        "name": place_name,
                        "place_type": place_type,
                        "state": row["STATE"],
                        "state_fips": row["STATEFP"],
                        "county": county.name,
                        "county_fips": county.county_fips,
                        "place_fips": row["PLACEFP"],
                        "funcstat": row["FUNCSTAT"],
                        "source": PLACE_URL,
                    },
                    relative_path=place_path,
                ),
            )
            written += 1
    return written, unmatched


def write_county_subdivisions(
    *,
    text: str,
    counties_by_name: dict[tuple[str, str], County],
) -> tuple[int, int]:
    written = 0
    unmatched = 0
    rows = csv.DictReader(io.StringIO(text))
    for row in rows:
        county = counties_by_name.get((row["STATE"], name_key(row["COUNTYNAME"])))
        if county is None:
            unmatched += 1
            continue

        cousub_name = row["COUSUBNAME"]
        cousub_path = (
            county.path
            / "county_subdivisions"
            / f"{slugify(cousub_name)}__{row['STATEFP']}{row['COUNTYFP']}{row['COUSUBFP']}"
        )
        write_json(
            cousub_path / "_jurisdiction.json",
            placeholder_payload(
                jurisdiction={
                    "country": "US",
                    "state": row["STATE"],
                    "county": county.name,
                    "municipality": cousub_name,
                },
                geography={
                    "type": "county_subdivision",
                    "name": cousub_name,
                    "state": row["STATE"],
                    "state_fips": row["STATEFP"],
                    "county": county.name,
                    "county_fips": row["COUNTYFP"],
                    "county_subdivision_fips": row["COUSUBFP"],
                    "funcstat": row["FUNCSTAT"],
                    "source": COUSUB_URL,
                },
                relative_path=cousub_path,
            ),
        )
        written += 1
    return written, unmatched


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate US jurisdiction placeholder tree.")
    parser.add_argument("--root", default="jurisdiction-catalog", help="Output directory")
    parser.add_argument("--clean", action="store_true", help="Delete existing root before writing")
    parser.add_argument(
        "--include-cdps",
        action="store_true",
        help="Also create municipality placeholders for Census Designated Places",
    )
    parser.add_argument(
        "--skip-county-subdivisions",
        action="store_true",
        help="Skip county subdivision placeholders",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Download timeout in seconds")
    args = parser.parse_args()

    root = Path(args.root)
    if args.clean and root.exists():
        shutil.rmtree(root)

    print("Downloading Census county reference data...")
    county_text = download_text(COUNTY_URL, args.timeout)
    counties, counties_by_name = parse_counties(county_text, root)

    write_root_files(root)
    write_states_and_counties(root, counties)

    print("Downloading Census place reference data...")
    place_text = download_text(PLACE_URL, args.timeout)
    municipalities_written, municipality_unmatched = write_municipalities(
        text=place_text,
        root=root,
        counties_by_name=counties_by_name,
        include_cdps=args.include_cdps,
    )

    subdivisions_written = 0
    subdivisions_unmatched = 0
    if not args.skip_county_subdivisions:
        print("Downloading Census county subdivision reference data...")
        cousub_text = download_text(COUSUB_URL, args.timeout)
        subdivisions_written, subdivisions_unmatched = write_county_subdivisions(
            text=cousub_text,
            counties_by_name=counties_by_name,
        )

    states_written = len({county.state for county in counties})
    summary = {
        "states": states_written,
        "counties": len(counties),
        "municipalities": municipalities_written,
        "municipalities_unmatched": municipality_unmatched,
        "county_subdivisions": subdivisions_written,
        "county_subdivisions_unmatched": subdivisions_unmatched,
    }
    write_json(root / "_generation_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

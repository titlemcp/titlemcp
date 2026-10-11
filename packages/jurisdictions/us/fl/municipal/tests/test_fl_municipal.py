from __future__ import annotations

import json
import re
import tomllib
import unittest
from datetime import date
from pathlib import Path

from titlemcp_us_fl_municipal.adapters import FloridaMunicipalLienSearchAdapter
from titlemcp_us_fl_municipal.connector import FloridaMunicipalDirectory
from titlemcp_us_fl_municipal.directory import DATA, FloridaDirectory, load_directory
from titlemcp_us_fl_municipal.manifest import capability_manifest

from title_mcp.domain.models import Jurisdiction, WorkflowKind, WorkflowRequest
from title_mcp.domain.municipal import GovernmentKind, MunicipalOffice
from title_mcp.sources import MunicipalDirectory, SourceKind, SourceResultStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 12)
PHONE = re.compile(r"\(?\d{3}\)?[-. ]+\d{3}-\d{4}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _office(name: str, kind: str = "municipality", county: str = "Sample County", **fields):
    return MunicipalOffice.model_validate(
        {
            "name": name,
            "kind": kind,
            "state": "FL",
            "county": county,
            "checked_on": "2026-10-11",
            "confidence": "high",
            **fields,
        }
    )


SAMPLE_COUNTY = _office(
    "Sample County",
    kind="county",
    lien_letter={
        "offered": "yes",
        "issuer": "Code Enforcement",
        "channel": "email",
        "request_email": "liens@county.example",
        "source_url": "https://county.example/liens",
        "fee_per_parcel": 45,
        "covers": ["code_violations", "code_liens"],
    },
    permits={"url": "https://permits.county.example", "platform": "energov"},
    special_assessments={"billing": "tax_bill"},
)
FORT_SAMPLE = _office(
    "Fort Sample",
    lien_letter={
        "offered": "yes",
        "issuer": "Finance Department",
        "channel": "online_portal",
        "request_url": "https://orders.example/fortsample",
        "vendor": "Example Lien Portal",
        "fee_per_parcel": 125,
        "turnaround": "5 business days",
        "covers": ["code_violations", "code_liens", "utilities"],
    },
    permits={
        "url": "https://permits.fortsample.example",
        "platform": "accela",
        "platform_name": "Accela Citizen Access",
        "search_by": ["address", "parcel"],
    },
    special_assessments={"billing": "direct", "office": "Public Works"},
)
SAINT_EXAMPLE = _office("Saint Example Beach")
SAMPLE_CITY = _office("Sample City")
QUIET_TOWN = _office("Quiet Lake", lien_letter={"offered": "unknown", "channel": "none_found"})
DIRECTORY = FloridaDirectory([SAMPLE_COUNTY, FORT_SAMPLE, SAINT_EXAMPLE, SAMPLE_CITY, QUIET_TOWN])


class NameMatchingTests(unittest.TestCase):
    def test_a_city_is_found_the_ways_people_write_it(self) -> None:
        for name in ("Fort Sample", "Ft. Sample", "City of Fort Sample", "fort sample city"):
            with self.subTest(name=name):
                self.assertIs(DIRECTORY.municipality(name, "Sample"), FORT_SAMPLE)

    def test_saint_and_its_abbreviation_are_one_name(self) -> None:
        self.assertIs(DIRECTORY.municipality("St. Example Beach"), SAINT_EXAMPLE)

    def test_a_city_named_city_keeps_its_name(self) -> None:
        self.assertIs(DIRECTORY.municipality("Sample City"), SAMPLE_CITY)
        self.assertIs(DIRECTORY.municipality("Sample City city"), SAMPLE_CITY)

    def test_a_county_is_found_with_or_without_county(self) -> None:
        self.assertIs(DIRECTORY.county("Sample"), SAMPLE_COUNTY)
        self.assertIs(DIRECTORY.county("sample county"), SAMPLE_COUNTY)
        self.assertIsNone(DIRECTORY.county("Other"))


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.connector = FloridaMunicipalDirectory(directory=DIRECTORY, today=TODAY)

    def test_the_connector_is_a_municipal_directory(self) -> None:
        self.assertIsInstance(self.connector, MunicipalDirectory)
        self.assertTrue(
            self.connector.supports(Jurisdiction(state="FL", county="Any"), SourceKind.MUNICIPAL)
        )
        self.assertFalse(self.connector.supports(Jurisdiction(state="GA", county="Any")))
        self.assertFalse(
            self.connector.supports(Jurisdiction(state="FL"), SourceKind.TAX_AUTHORITY)
        )

    async def test_a_city_answer_carries_the_city_and_its_county(self) -> None:
        result = await self.connector.find_offices(
            Jurisdiction(state="FL", county="Sample County", municipality="Ft. Sample")
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertTrue(result.requires_human_review)
        [record] = result.records
        self.assertEqual(record["schema_name"], "title_mcp.municipal_lien_directory")
        self.assertEqual(record["municipality"]["name"], "Fort Sample")
        self.assertEqual(record["municipality"]["lien_letter"]["fee_per_parcel"], "125")
        self.assertEqual(record["county"]["name"], "Sample County")
        self.assertIn("unincorporated area", " ".join(record["notes"]))

    async def test_a_town_not_in_the_directory_gets_the_county_and_the_coverage(self) -> None:
        result = await self.connector.find_offices(
            Jurisdiction(state="FL", county="Sample County", municipality="Tiny Hamlet")
        )

        self.assertIs(result.status, SourceResultStatus.PARTIAL)
        self.assertEqual(result.records[0]["county"]["name"], "Sample County")
        self.assertIn("cities of 20,000 people or more", result.warnings[0])

    async def test_unincorporated_means_the_county_alone(self) -> None:
        result = await self.connector.find_offices(
            Jurisdiction(state="FL", county="Sample", municipality="Unincorporated")
        )

        self.assertIs(result.status, SourceResultStatus.SUCCEEDED)
        self.assertIsNone(result.records[0]["jurisdiction"]["municipality"])

    async def test_a_county_not_in_the_directory_is_no_results(self) -> None:
        result = await self.connector.find_offices(Jurisdiction(state="FL", county="Other"))

        self.assertIs(result.status, SourceResultStatus.NO_RESULTS)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.adapter = FloridaMunicipalLienSearchAdapter(directory=DIRECTORY)

    async def _plan(self, county: str, municipality: str | None = None):
        request = WorkflowRequest(
            kind=WorkflowKind.MUNICIPAL_LIEN_SEARCH,
            jurisdiction=Jurisdiction(state="FL", county=county, municipality=municipality),
            order={"file_number": "TEST-0001"},
        )
        return await self.adapter.plan(request)

    def test_it_plans_florida_counties_in_the_directory(self) -> None:
        self.assertTrue(self.adapter.supports(Jurisdiction(state="FL", county="Sample")))
        self.assertFalse(self.adapter.supports(Jurisdiction(state="FL", county="Other")))
        self.assertFalse(self.adapter.supports(Jurisdiction(state="GA", county="Sample")))

    async def test_the_first_step_says_how_to_order_the_citys_letter(self) -> None:
        plan = await self._plan("Sample", "Fort Sample")

        first = plan.steps[0]
        self.assertEqual(first.label, "Order Fort Sample's lien letter")
        self.assertIn(
            "through Example Lien Portal at https://orders.example/fortsample", first.description
        )
        self.assertIn("$125.00 a parcel", first.description)
        self.assertIn("5 business days", first.description)
        self.assertEqual(first.metadata["tool"], "municipal_lien_directory")

    async def test_only_what_the_letter_leaves_out_gets_its_own_step(self) -> None:
        plan = await self._plan("Sample", "Fort Sample")

        labels = [step.label for step in plan.steps]
        self.assertIn("Check open and expired permits", labels)
        self.assertNotIn("Check code cases and code liens", labels)
        self.assertNotIn("Check utility balances", labels)
        permits = next(step for step in plan.steps if step.label.startswith("Check open"))
        self.assertIn("https://permits.fortsample.example", permits.description)
        self.assertIn("by address, parcel", permits.description)
        self.assertEqual(plan.steps[-1].label, "Review the search results")

    async def test_an_emailed_request_names_the_address(self) -> None:
        plan = await self._plan("Sample County")

        self.assertIn("Email a request to liens@county.example", plan.steps[0].description)
        self.assertEqual(plan.routing_hints["channel"], "email")

    async def test_no_published_process_says_to_ask_the_offices(self) -> None:
        plan = await self._plan("Sample", "Quiet Lake")

        self.assertEqual(plan.steps[0].label, "Ask Quiet Lake for its lien information")

    def test_a_town_not_in_the_directory_is_left_to_the_general_plan(self) -> None:
        town = Jurisdiction(state="FL", county="Sample", municipality="Tiny Hamlet")
        unincorporated = Jurisdiction(state="FL", county="Sample", municipality="Unincorporated")

        self.assertFalse(self.adapter.supports(town))
        self.assertTrue(self.adapter.supports(unincorporated))

    async def test_a_free_letter_says_so(self) -> None:
        directory = FloridaDirectory(
            [
                _office(
                    "Sample County",
                    kind="county",
                    lien_letter={"offered": "yes", "channel": "online_portal", "fee_per_parcel": 0},
                )
            ]
        )
        request = WorkflowRequest(
            kind=WorkflowKind.MUNICIPAL_LIEN_SEARCH,
            jurisdiction=Jurisdiction(state="FL", county="Sample"),
            order={"file_number": "TEST-0001"},
        )

        plan = await FloridaMunicipalLienSearchAdapter(directory=directory).plan(request)

        self.assertIn("There's no fee.", plan.steps[0].description)

    async def test_a_letter_asked_for_by_phone_says_to_ask_the_office(self) -> None:
        directory = FloridaDirectory(
            [
                _office(
                    "Sample County",
                    kind="county",
                    lien_letter={
                        "offered": "yes",
                        "channel": "phone",
                        "source_url": "https://county.example/liens",
                    },
                )
            ]
        )
        request = WorkflowRequest(
            kind=WorkflowKind.MUNICIPAL_LIEN_SEARCH,
            jurisdiction=Jurisdiction(state="FL", county="Sample"),
            order={"file_number": "TEST-0001"},
        )

        plan = await FloridaMunicipalLienSearchAdapter(directory=directory).plan(request)

        self.assertIn(
            "Ask Sample County how to order it; it's described at https://county.example/liens.",
            plan.steps[0].description,
        )


class DirectoryDataTests(unittest.TestCase):
    def test_every_county_and_its_cities_are_in_the_directory(self) -> None:
        directory = load_directory()
        counties = [o for o in directory.offices if o.kind is GovernmentKind.COUNTY]
        cities = [o for o in directory.offices if o.kind is GovernmentKind.MUNICIPALITY]

        self.assertEqual(len(counties), 67)
        self.assertGreaterEqual(len(cities), 120)
        for city in cities:
            with self.subTest(city=city.name):
                self.assertIsNotNone(directory.county(city.county))
                self.assertIs(directory.municipality(city.name, city.county), city)

    def test_common_spellings_find_their_place(self) -> None:
        directory = load_directory()

        self.assertEqual(directory.county("Dade").name, "Miami-Dade County")
        self.assertEqual(directory.county("De Soto").name, "DeSoto County")
        self.assertEqual(directory.county("St. Johns").name, "St. Johns County")
        self.assertEqual(directory.municipality("Port Saint Lucie").name, "Port St. Lucie")
        self.assertEqual(directory.municipality("Haines City").name, "Haines City")

    def test_the_data_holds_no_phone_numbers_or_personal_addresses(self) -> None:
        entries = json.loads(DATA.read_text("utf-8"))
        for entry in entries:
            letter = entry["lien_letter"]
            text = json.dumps({**entry, "lien_letter": {**letter, "request_email": None}})
            with self.subTest(entry=entry["name"]):
                self.assertIsNone(PHONE.search(text))
                for address in EMAIL.findall(text):
                    self.assertTrue(letter["request_url"].startswith(f"mailto:{address}"))

    def test_every_link_is_a_web_page_or_a_mail_address(self) -> None:
        entries = json.loads(DATA.read_text("utf-8"))
        for entry in entries:
            for value in _urls(entry):
                with self.subTest(entry=entry["name"], url=value):
                    self.assertRegex(value, r"^(https?://|mailto:)")


def _urls(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("url", "website") or key.endswith("_url") or key == "billing_portal":
                if item:
                    yield item
            else:
                yield from _urls(item)


class ManifestTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])
        self.assertEqual(manifest.version, readiness["capability"]["version"])
        self.assertIn(WorkflowKind.MUNICIPAL_LIEN_SEARCH, manifest.workflow_kinds)
        self.assertTrue(readiness["workflows"]["municipal_lien_search"]["human_review_required"])

    def test_pyproject_entry_points_match_the_manifest(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file)["project"]
        entry_points = project["entry-points"]
        manifest = capability_manifest()

        for group, target in manifest.entry_points.items():
            with self.subTest(group=group):
                self.assertIn(target, entry_points[group].values())


if __name__ == "__main__":
    unittest.main()

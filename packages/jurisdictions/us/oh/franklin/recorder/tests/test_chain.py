"""Assembling a chain for one parcel out of a countywide name search.

The fixture is a real response from the county, trimmed. It contains one
party's documents across three properties, two of which sit in subdivisions
with nearly the same name. That is not contrived: it is what a common search
returns, and every assertion here is a mistake the obvious implementation
makes.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from titlemcp_us_oh_franklin_recorder import chain
from titlemcp_us_oh_franklin_recorder.client import RecorderDocument, _to_result

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "name_search.json"

SUBJECT_PARCEL = "030-000526-00"
OWNER = "ZWINK ROBERT V"


def load() -> list[RecorderDocument]:
    return _to_result(json.loads(FIXTURE.read_text())).documents


class ParcelScopingTests(unittest.TestCase):
    def test_a_name_search_returns_more_than_one_property(self) -> None:
        """The premise. Without this, scoping would not be needed."""
        parcels = set()
        for document in load():
            parcels |= chain.parcels_in(document.legal_description)
        self.assertGreater(len(parcels), 1)

    def test_scoping_keeps_only_the_subject_parcel(self) -> None:
        scoped = [d for d in load() if chain.on_parcel(d, SUBJECT_PARCEL)]
        self.assertTrue(scoped)
        for document in scoped:
            self.assertIn("030-000526", document.legal_description)

    def test_a_neighbouring_subdivision_with_a_similar_name_is_excluded(self) -> None:
        """``FRANK S WAGENHALS ET AL`` and ``WAGENHALS ET AL`` are two places.

        Matching on the subdivision name picks up both and reports the wrong
        lender with complete confidence.
        """
        scoped = [d for d in load() if chain.on_parcel(d, SUBJECT_PARCEL)]
        self.assertFalse(any("030-000001" in d.legal_description for d in scoped))

    def test_the_trailing_pair_of_a_parcel_number_is_optional(self) -> None:
        document = RecorderDocument(legal_description="Lt/Un 193 SOMETHING Pcl# 030-000526 Plt")
        self.assertTrue(chain.on_parcel(document, "030-000526-00"))

    def test_a_parcel_that_appears_nowhere_yields_a_note_not_a_guess(self) -> None:
        built = chain.build(parcel_id="999-999999-99", owner_name=OWNER, documents=load())
        self.assertEqual(built.documents_on_parcel, 0)
        self.assertIsNone(built.acquisition)
        self.assertTrue(built.notes)


class AcquisitionTests(unittest.TestCase):
    def test_the_acquisition_is_the_deed_naming_the_owner_as_grantee(self) -> None:
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        self.assertIsNotNone(built.acquisition)
        assert built.acquisition is not None
        self.assertEqual(built.acquisition.instrument_number, "202104120064304")
        self.assertTrue(any("ZWINK" in name for name in built.acquisition.grantees))

    def test_a_deed_where_the_owner_is_the_grantor_is_not_an_acquisition(self) -> None:
        """The same party sold a different property a fortnight after buying.

        Taking the nearest deed by date picks that one up and dates the chain
        from a sale.
        """
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        assert built.acquisition is not None
        self.assertNotEqual(built.acquisition.instrument_number, "202104270074438")


class OpenLienTests(unittest.TestCase):
    def test_the_open_mortgage_is_found(self) -> None:
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        self.assertEqual(len(built.open_liens), 1)
        self.assertEqual(built.open_liens[0].instrument_number, "202104120064305")

    def test_the_lender_is_reported_and_the_nominee_is_not(self) -> None:
        """MERS holds title as nominee. A payoff never comes from it."""
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        lien = built.open_liens[0]
        self.assertEqual(lien.lenders, ["BETTER MORTGAGE CORP"])
        self.assertTrue(any("MERS" in name for name in lien.nominees))
        for name in lien.lenders:
            self.assertNotIn("ELECTRONIC REGISTRATION", name)

    def test_a_mortgage_recorded_after_its_deed_is_purchase_money(self) -> None:
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        self.assertTrue(built.open_liens[0].is_purchase_money)

    def test_a_released_mortgage_is_not_reported_as_open(self) -> None:
        documents = [
            RecorderDocument(
                document_type="DEED",
                instrument_number="1000",
                recorded_date="1/1/2020",
                grantees=["SMITH JOHN"],
                legal_description="Pcl# 030-000526-00",
            ),
            RecorderDocument(
                document_type="MORTGAGE",
                instrument_number="1001",
                recorded_date="1/1/2020",
                grantors=["SMITH JOHN"],
                grantees=["HUNTINGTON NATIONAL BANK"],
                legal_description="Pcl# 030-000526-00",
            ),
            RecorderDocument(
                document_type="RELEASE OF MORTGAGE",
                instrument_number="2000",
                recorded_date="6/1/2022",
                grantees=["HUNTINGTON NATIONAL BANK"],
                legal_description="Pcl# 030-000526-00",
            ),
        ]
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name="SMITH JOHN", documents=documents)
        self.assertEqual(built.open_liens, [])
        self.assertEqual(built.released, ["1001"])

    def test_a_release_recorded_before_the_mortgage_does_not_discharge_it(self) -> None:
        """A refinance leaves an old release above a newer mortgage."""
        documents = [
            RecorderDocument(
                document_type="RELEASE OF MORTGAGE",
                instrument_number="900",
                recorded_date="1/1/2019",
                grantees=["HUNTINGTON NATIONAL BANK"],
                legal_description="Pcl# 030-000526-00",
            ),
            RecorderDocument(
                document_type="DEED",
                instrument_number="1000",
                recorded_date="1/1/2020",
                grantees=["SMITH JOHN"],
                legal_description="Pcl# 030-000526-00",
            ),
            RecorderDocument(
                document_type="MORTGAGE",
                instrument_number="1001",
                recorded_date="1/1/2020",
                grantors=["SMITH JOHN"],
                grantees=["HUNTINGTON NATIONAL BANK"],
                legal_description="Pcl# 030-000526-00",
            ),
        ]
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name="SMITH JOHN", documents=documents)
        self.assertEqual(len(built.open_liens), 1)

    def test_the_result_always_asks_for_review(self) -> None:
        """The index does not link a release to the mortgage it discharges."""
        built = chain.build(parcel_id=SUBJECT_PARCEL, owner_name=OWNER, documents=load())
        self.assertTrue(built.requires_human_review)


class ClassificationTests(unittest.TestCase):
    def test_document_types_map_to_what_they_mean(self) -> None:
        cases = {
            "DEED": chain.InstrumentKind.DEED,
            "SHERIFFS DEED": chain.InstrumentKind.DEED,
            "MORTGAGE": chain.InstrumentKind.MORTGAGE,
            "RELEASE OF MORTGAGE": chain.InstrumentKind.RELEASE,
            "ASSIGN OF MORTGAGE": chain.InstrumentKind.ASSIGNMENT,
            "EASEMENT": chain.InstrumentKind.OTHER,
        }
        for document_type, expected in cases.items():
            with self.subTest(document_type=document_type):
                self.assertIs(chain.classify(document_type), expected)

    def test_a_release_is_classified_before_a_mortgage(self) -> None:
        """"RELEASE OF MORTGAGE" contains both words; order decides."""
        self.assertIs(chain.classify("RELEASE OF MORTGAGE"), chain.InstrumentKind.RELEASE)
        self.assertIs(chain.classify("ASSIGN OF MORTGAGE"), chain.InstrumentKind.ASSIGNMENT)


if __name__ == "__main__":
    unittest.main()

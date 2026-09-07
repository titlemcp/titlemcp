from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from titlemcp_us_oh_franklin_recorder.adapters import FranklinCountyOhioRecorderAdapter
from titlemcp_us_oh_franklin_recorder.manifest import capability_manifest
from titlemcp_us_oh_franklin_recorder.sources import FranklinRecorderSourceConnector

from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.sources import SourceKind

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class FranklinRecorderContractTests(unittest.TestCase):
    def test_manifest_matches_package_readiness_file(self) -> None:
        manifest = capability_manifest()
        with (PACKAGE_ROOT / "titlemcp-capability.toml").open("rb") as readiness_file:
            readiness = tomllib.load(readiness_file)

        self.assertEqual(manifest.capability_id, readiness["capability"]["capability_id"])
        self.assertEqual(manifest.package_name, readiness["capability"]["package_name"])

    def test_adapter_supports_franklin_county_public_records(self) -> None:
        adapter = FranklinCountyOhioRecorderAdapter()

        self.assertTrue(
            adapter.supports(Jurisdiction(country="US", state="OH", county="Franklin County"))
        )
        self.assertIn(WorkflowKind.PUBLIC_RECORDS_SEARCH, adapter.workflow_kinds)

    def test_source_supports_franklin_county_recorder(self) -> None:
        source = FranklinRecorderSourceConnector("https://example.invalid")

        self.assertTrue(
            source.supports(
                Jurisdiction(country="US", state="OH", county="Franklin County"),
                SourceKind.COUNTY_RECORDER,
            )
        )

    def test_the_source_needs_no_credential(self) -> None:
        """The county issues a session to anyone who asks for the page.

        There is nothing to configure and nothing to store, which is why this
        connector has no credential path.
        """
        source = FranklinRecorderSourceConnector("https://example.invalid")

        self.assertFalse(source.descriptor.requires_auth)


if __name__ == "__main__":
    unittest.main()

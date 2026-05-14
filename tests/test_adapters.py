from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from title_mcp.adapters import create_default_adapter_registry
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class AdapterRegistryTests(unittest.TestCase):
    def test_resolves_state_specific_adapter_before_generic(self) -> None:
        registry = create_default_adapter_registry()

        self.assertEqual(
            registry.resolve(Jurisdiction(state="FL", county="Orange")).adapter_id,
            "florida",
        )
        self.assertEqual(
            registry.resolve(Jurisdiction(state="KY", county="Wayne")).adapter_id,
            "generic",
        )

    def test_resolves_workflow_specific_city_adapter(self) -> None:
        registry = create_default_adapter_registry()
        jurisdiction = Jurisdiction(
            country="US",
            state="MD",
            county="Baltimore",
            municipality="Baltimore City",
        )

        self.assertEqual(
            registry.resolve(jurisdiction, WorkflowKind.PUBLIC_RECORDS_SEARCH).adapter_id,
            "us-md-baltimore-city-public-records",
        )
        self.assertEqual(
            registry.resolve(jurisdiction, WorkflowKind.TAX_CERTIFICATE).adapter_id,
            "generic",
        )

    def test_resolves_county_alias_adapter(self) -> None:
        registry = create_default_adapter_registry()

        self.assertEqual(
            registry.resolve(
                Jurisdiction(country="US", state="FL", county="Dade"),
                WorkflowKind.PUBLIC_RECORDS_SEARCH,
            ).adapter_id,
            "us-fl-miami-dade-public-records",
        )

    def test_loads_configured_jurisdiction_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "jurisdictions.json"
            config_path.write_text(
                json.dumps(
                    {
                        "adapters": [
                            {
                                "adapter_id": "us-md-baltimore-county-public-records",
                                "priority": 200,
                                "scope": {
                                    "country": "US",
                                    "state": "MD",
                                    "county": "Baltimore County",
                                },
                                "workflow_kinds": ["public_records_search"],
                                "steps": [
                                    {
                                        "label": "Search Baltimore County land records",
                                        "description": "Configured public records route.",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            registry = create_default_adapter_registry(config_path=config_path)

            self.assertEqual(
                registry.resolve(
                    Jurisdiction(country="US", state="MD", county="Baltimore County"),
                    WorkflowKind.PUBLIC_RECORDS_SEARCH,
                ).adapter_id,
                "us-md-baltimore-county-public-records",
            )


if __name__ == "__main__":
    unittest.main()

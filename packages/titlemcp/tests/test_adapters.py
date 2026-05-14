from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from title_mcp.adapters import AdapterRegistry, create_default_adapter_registry
from title_mcp.domain.models import Jurisdiction, WorkflowKind


class AdapterRegistryTests(unittest.TestCase):
    def test_register_replaces_duplicate_adapter_id(self) -> None:
        registry = AdapterRegistry()
        first = _FakeAdapter("duplicate", priority=10)
        second = _FakeAdapter("duplicate", priority=20)

        registry.register(first)
        registry.register(second)

        self.assertEqual(registry.all(), [second])

    def test_loads_adapter_entry_points(self) -> None:
        entry_point = _FakeEntryPoint(_FakeAdapter("entry-point-adapter", priority=300))

        with patch("title_mcp.adapters.registry.entry_points", return_value=[entry_point]):
            registry = create_default_adapter_registry(include_entry_points=True)

        self.assertEqual(
            registry.resolve(
                Jurisdiction(country="US", state="OH", county="Franklin County"),
                WorkflowKind.PUBLIC_RECORDS_SEARCH,
            ).adapter_id,
            "entry-point-adapter",
        )

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


class _FakeAdapter:
    workflow_kinds = frozenset({WorkflowKind.PUBLIC_RECORDS_SEARCH})

    def __init__(self, adapter_id: str, priority: int) -> None:
        self.adapter_id = adapter_id
        self.priority = priority

    def supports(self, jurisdiction: Jurisdiction) -> bool:
        return jurisdiction.matches(country="US", state="OH", county="Franklin County")


class _FakeEntryPoint:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self._adapter = adapter

    def load(self):
        return lambda: self._adapter


if __name__ == "__main__":
    unittest.main()

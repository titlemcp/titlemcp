from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import title_mcp

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_project_package_name(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject:
            metadata = tomllib.load(pyproject)

        self.assertEqual(metadata["project"]["name"], "titlemcp")

    def test_version_matches_project_metadata(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject:
            metadata = tomllib.load(pyproject)

        self.assertEqual(title_mcp.__version__, metadata["project"]["version"])

    def test_jurisdiction_extra_points_to_package(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject:
            metadata = tomllib.load(pyproject)

        extras = metadata["project"]["optional-dependencies"]
        self.assertIn("us-oh-franklin", extras)
        self.assertIn(
            "titlemcp-us-oh-franklin-recorder>=0.1.0",
            extras["us-oh-franklin"],
        )

    def test_only_titlemcp_console_scripts_are_exported(self) -> None:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject:
            metadata = tomllib.load(pyproject)

        scripts = metadata["project"]["scripts"]
        self.assertIn("titlemcp-server", scripts)
        self.assertIn("titlemcp-ollama", scripts)
        self.assertNotIn("title-mcp-server", scripts)
        self.assertNotIn("title-mcp-ollama", scripts)

    def test_package_exports_typed_marker(self) -> None:
        self.assertTrue((PACKAGE_ROOT / "src/title_mcp/py.typed").is_file())


if __name__ == "__main__":
    unittest.main()

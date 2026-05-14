from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import title_mcp


class PackagingTests(unittest.TestCase):
    def test_version_matches_project_metadata(self) -> None:
        with Path("pyproject.toml").open("rb") as pyproject:
            metadata = tomllib.load(pyproject)

        self.assertEqual(title_mcp.__version__, metadata["project"]["version"])

    def test_package_exports_typed_marker(self) -> None:
        self.assertTrue(Path("src/title_mcp/py.typed").is_file())


if __name__ == "__main__":
    unittest.main()

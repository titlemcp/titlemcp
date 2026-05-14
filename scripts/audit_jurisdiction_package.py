from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

REQUIRED_READINESS_FLAGS = [
    "docs",
    "unit_tests",
    "fixtures",
    "integration_tests",
    "no_live_credentials",
    "pypi_metadata",
    "reviewer_approved",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a TitleMCP jurisdiction package.")
    parser.add_argument("package_path", type=Path)
    parser.add_argument(
        "--require-publish-ready",
        action="store_true",
        help="Fail unless readiness flags and release.publish are complete.",
    )
    args = parser.parse_args()

    package_path = args.package_path.resolve()
    errors = audit_package(package_path, require_publish_ready=args.require_publish_ready)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: {package_path}")
    return 0


def audit_package(package_path: Path, *, require_publish_ready: bool) -> list[str]:
    errors: list[str] = []
    readiness_path = package_path / "titlemcp-capability.toml"
    pyproject_path = package_path / "pyproject.toml"

    for path in [
        pyproject_path,
        package_path / "README.md",
        package_path / "src",
        package_path / "tests",
        readiness_path,
    ]:
        if not path.exists():
            errors.append(f"missing required path: {path}")

    if errors:
        return errors

    with readiness_path.open("rb") as readiness_file:
        readiness = tomllib.load(readiness_file)
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    capability = readiness.get("capability", {})
    project = pyproject.get("project", {})
    if capability.get("package_name") != project.get("name"):
        errors.append("capability.package_name must match project.name")
    if capability.get("version") != project.get("version"):
        errors.append("capability.version must match project.version")

    entry_points = project.get("entry-points", {})
    for group in ["title_mcp.adapters", "title_mcp.capabilities"]:
        if group not in entry_points:
            errors.append(f"missing entry point group: {group}")

    readiness_flags: dict[str, Any] = readiness.get("readiness", {})
    if readiness_flags.get("no_live_credentials") is not True:
        errors.append("readiness.no_live_credentials must be true")
    if readiness_flags.get("pypi_metadata") is not True:
        errors.append("readiness.pypi_metadata must be true")

    if require_publish_ready:
        for flag in REQUIRED_READINESS_FLAGS:
            if readiness_flags.get(flag) is not True:
                errors.append(f"readiness.{flag} must be true before publishing")

        release = readiness.get("release", {})
        if release.get("publish") is not True:
            errors.append("release.publish must be true before publishing")

        for workflow_name, workflow in readiness.get("workflows", {}).items():
            if workflow.get("status") != "ready":
                errors.append(f"workflows.{workflow_name}.status must be ready before publishing")
            if workflow.get("human_review_required") is not True:
                errors.append(
                    f"workflows.{workflow_name}.human_review_required must be true"
                )

    return errors


if __name__ == "__main__":
    raise SystemExit(main())

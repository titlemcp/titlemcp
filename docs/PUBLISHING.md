# Publishing

This project is packaged with `hatchling` and can be published to a Python package index as a
source distribution and wheel.

## 1. Choose The Release Target

For private or commercial deployments, publish to a private package index such as an internal
devpi, Artifactory, Nexus, GitHub Packages, or AWS CodeArtifact repository.

For public PyPI, confirm that:

- The package name is available.
- `LICENSE` and `pyproject.toml` contain the actual license you intend to grant.
- The README does not disclose private customer, vendor, credential, or workflow information.
- Example jurisdiction config files do not disclose private vendor credentials or customer data.
- Generated jurisdiction placeholders are intentionally excluded from the wheel to keep package
  installs small.

Check current public package name usage before release:

```bash
.venv/bin/python -m pip index versions razi-title-mcp
```

`No matching distribution found` means pip did not find a public release under that name at the
time you checked.

## 2. Prepare The Environment

```bash
.venv/bin/pip install -e ".[publish]"
```

## 3. Clean And Build

```bash
rm -rf dist build *.egg-info
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## 4. Publish To TestPyPI

```bash
.venv/bin/python -m twine upload --repository testpypi dist/*
```

Install from TestPyPI in a clean environment:

```bash
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  razi-title-mcp
```

## 5. Publish To PyPI

```bash
.venv/bin/python -m twine upload dist/*
```

Prefer PyPI trusted publishing for automated releases instead of long-lived API tokens. The
included GitHub Actions workflow is configured for trusted publishing once the project is linked
in PyPI.

## Versioning

Update `project.version` in `pyproject.toml` for each release. Use normal semantic versioning
while the public API is still forming:

- Patch releases for bug fixes.
- Minor releases for backward-compatible features.
- Major releases for breaking API changes.

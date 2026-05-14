# Publishing

The core `titlemcp` package and each jurisdiction package are packaged with `hatchling` and can be
published independently as source distributions and wheels.

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
- Reusable jurisdiction implementations should usually be published as separate `titlemcp-*`
  packages instead of bundled into the core package.
- If you add a `titlemcp[...]` jurisdiction extra, publish the referenced jurisdiction package to
  the same index before releasing the core package metadata that depends on it.

Check current public package name usage before release:

```bash
.venv/bin/python -m pip index versions titlemcp
```

`No matching distribution found` means pip did not find a public release under that name at the
time you checked.

## 2. Prepare The Environment

```bash
.venv/bin/pip install -e "packages/titlemcp[publish]"
```

## 3. Clean And Build

```bash
cd packages/titlemcp
../../.venv/bin/python -m build
../../.venv/bin/python -m twine check dist/*
```

For a jurisdiction package, run the same commands from its package directory, for example:

```bash
cd packages/jurisdictions/us/oh/franklin/recorder
../../../../../../.venv/bin/python -m build
../../../../../../.venv/bin/python -m twine check dist/*
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
  titlemcp
```

## 5. Publish To PyPI

```bash
.venv/bin/python -m twine upload dist/*
```

Prefer PyPI trusted publishing for automated releases instead of long-lived API tokens. The
included GitHub Actions workflow accepts a `package-path` input so the same workflow can publish
`packages/titlemcp` or any ready jurisdiction package once that PyPI project trusts the workflow.

## Versioning

Update `project.version` in `pyproject.toml` for each release. Use normal semantic versioning
while the public API is still forming:

- Patch releases for bug fixes.
- Minor releases for backward-compatible features.
- Major releases for breaking API changes.

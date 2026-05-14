# Jurisdiction Structure

Jurisdiction-specific package code lives under `packages/jurisdictions/`. Generated jurisdiction
reference placeholders live under `jurisdiction-catalog/`.

The generated convention is:

```text
jurisdiction-catalog/
  _templates/
    capability_package/
      adapters/
      schemas/
      tests/
      tools/
      workflows/
  US/
    _jurisdiction.json
    states/
      MD/
        _jurisdiction.json
        counties/
          baltimore_city__24510/
            _jurisdiction.json
            capabilities/
              .gitkeep
            municipalities/
              baltimore_city__2404000/
                _jurisdiction.json
                capabilities/
                  .gitkeep
```

Create new capability files under the relevant jurisdiction directory. Keep shared workflow logic in
`packages/titlemcp/src/title_mcp`, and put reusable jurisdiction-specific source routing, vendor
rules, and public-record variations under `packages/jurisdictions/`.

Each jurisdiction directory has:

- `_jurisdiction.json` with identity, source geography, and capability convention metadata.
- `capabilities/` as the local placeholder for jurisdiction-specific code, configs, schemas, and tests.

## Generate Or Refresh

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean
```

By default, the generator creates:

- U.S. states and state-equivalent Census jurisdictions.
- Counties and county equivalents.
- Incorporated-place municipality placeholders.
- County subdivision placeholders.

The current generated tree contains 57 state/state-equivalent jurisdictions, 3,235 county/county
equivalent jurisdictions, 20,724 incorporated-place municipality placeholders, and 36,642 county
subdivision placeholders.

This is intentionally a large local workspace. The generated `jurisdiction-catalog/` tree is
excluded from Python wheels; the core package source distribution includes the generator script so
deployments can recreate or trim the tree as needed.

When a jurisdiction capability becomes reusable, move it into a separate pip package such as
`titlemcp-us-oh-franklin-recorder` and expose its manifest, adapter, source connector, and optional
vendor connector through entry points. See [JURISDICTION_PACKAGES.md](JURISDICTION_PACKAGES.md).

Add Census Designated Places when needed:

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean --include-cdps
```

Skip county subdivisions when you only want state/county/incorporated-place placeholders:

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean --skip-county-subdivisions
```

## Capability Rule Of Thumb

- Put reusable domain behavior in `packages/titlemcp/src/title_mcp/domain`,
  `packages/titlemcp/src/title_mcp/services`, or `packages/titlemcp/src/title_mcp/workflows`.
- Put shared MCP tool registration in `packages/titlemcp/src/title_mcp/mcp/tool_catalog.py`.
- Put state/county/municipality-specific package behavior under `packages/jurisdictions/`.
- Use `TITLE_MCP_JURISDICTION_CONFIG_PATH` for JSON-configured adapter routing.
- Use Python adapters when the jurisdiction needs custom integrations or nontrivial behavior.
- Use source connectors for public-record, tax, court, recorder, OCR, and government-system access.
- Use vendor connectors for third-party service-provider ordering and status.

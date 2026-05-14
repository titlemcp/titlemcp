# Jurisdiction Structure

Jurisdiction-specific capabilities live outside the package code in `jurisdictions/`.

The generated convention is:

```text
jurisdictions/
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
`src/title_mcp`, and put jurisdiction-specific source routing, vendor rules, and public-record
variations under `jurisdictions/`.

Each jurisdiction directory has:

- `_jurisdiction.json` with identity, source geography, and capability convention metadata.
- `capabilities/` as the local placeholder for jurisdiction-specific code, configs, schemas, and tests.

## Generate Or Refresh

```bash
.venv/bin/python scripts/generate_us_jurisdiction_tree.py --clean
```

By default, the generator creates:

- U.S. states and state-equivalent Census jurisdictions.
- Counties and county equivalents.
- Incorporated-place municipality placeholders.
- County subdivision placeholders.

The current generated tree contains 57 state/state-equivalent jurisdictions, 3,235 county/county
equivalent jurisdictions, 20,724 incorporated-place municipality placeholders, and 36,642 county
subdivision placeholders.

This is intentionally a large local workspace. The generated `jurisdictions/` tree is excluded from
the Python wheel; the source distribution includes the generator script so deployments can recreate
or trim the tree as needed.

Add Census Designated Places when needed:

```bash
.venv/bin/python scripts/generate_us_jurisdiction_tree.py --clean --include-cdps
```

Skip county subdivisions when you only want state/county/incorporated-place placeholders:

```bash
.venv/bin/python scripts/generate_us_jurisdiction_tree.py --clean --skip-county-subdivisions
```

## Capability Rule Of Thumb

- Put reusable domain behavior in `src/title_mcp/services` or `src/title_mcp/workflows`.
- Put MCP tool registration in `src/title_mcp/mcp/server.py` when it is a shared platform tool.
- Put state/county/municipality-specific behavior in the matching `jurisdictions/` directory.
- Use `TITLE_MCP_JURISDICTION_CONFIG_PATH` for JSON-configured adapter routing.
- Use Python adapters when the jurisdiction needs custom integrations or nontrivial behavior.

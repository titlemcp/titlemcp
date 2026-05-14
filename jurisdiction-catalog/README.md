# Jurisdiction Workspace

Generated placeholders for country, state, county, municipality, and county-subdivision specific title-operation capabilities.

Create new MCP capabilities in the relevant jurisdiction directory using the convention described in `_jurisdiction.json`. Regenerate this tree with:

```bash
.venv/bin/python packages/titlemcp/scripts/generate_us_jurisdiction_tree.py \
  --root jurisdiction-catalog --clean
```

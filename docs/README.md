# TitleMCP Docs

TitleMCP is a Python MCP server toolkit for title companies. It gives local
LLMs, hosted agents, and workflow systems structured tools for title and real
estate operations while keeping legal, underwriting, settlement, and recording
decisions in a human-review loop.

Start here if you are new to the project:

1. [Getting Started](GETTING_STARTED.md): install from a source checkout, run the
   MCP server, and verify the tool surface.
2. [Tool Reference](TOOLS.md): what tools exist today and what each returns.
3. [Configuration](CONFIGURATION.md): environment variables for PACER, state
   backends, logging, extension loading, and optional source connectors.
4. [Samples](SAMPLES.md): Ollama examples for Franklin County Auditor, HOA
   contact search, and PACER.
5. [Extending TitleMCP](EXTENDING.md): where to add adapters, source connectors,
   vendor connectors, domain models, and optional toolsets.
6. [Agent & contributor guide](../AGENTS.md): the conventions every agent and
   contributor must follow — Pydantic principles and the tool/test/sample
   contract for new endpoints.

## What TitleMCP Is

TitleMCP is built around MCP tools that return predictable domain records:

- `title_mcp.property_assessment_record` for county auditor and assessment
  sources.
- `title_mcp.hoa_contact_search` for HOA contact discovery.
- `title_mcp.parcel_record` for parcel/property data providers.
- `title_mcp.pacer_bankruptcy_search` for PACER bankruptcy party searches.
- Workflow response models for estoppels, municipal liens, tax certificates,
  document analysis, payoff parsing, release tracking, and review tasks.

Source-specific payloads are preserved under `source_specific` so downstream
systems can rely on stable canonical fields without losing evidence from the
original source.

## What TitleMCP Is Not

TitleMCP does not make autonomous legal, underwriting, disbursement, payoff,
recording, or curative decisions. Tools gather facts, normalize records, create
workflows, and make the state auditable. A human reviewer remains responsible
for title-impacting decisions.

## Repository Map

```text
packages/titlemcp/                         core Python package
packages/platforms/iasworld/               shared Tyler iasWorld auditor scraper
packages/jurisdictions/us/oh/franklin/     Franklin County recorder package
packages/jurisdictions/us/oh/auditor/      Ohio county auditor package (iasWorld)
samples/                                   runnable Ollama examples
docs/                                      beginner-facing documentation
packages/titlemcp/docs/                    deeper package architecture docs
jurisdiction-catalog/                      generated jurisdiction scaffolding
```

## Advanced Reference

The beginner docs in this folder point to deeper reference files when needed:

- [Core architecture](../packages/titlemcp/docs/ARCHITECTURE.md)
- [Jurisdiction packages](../packages/titlemcp/docs/JURISDICTION_PACKAGES.md)
- [Jurisdiction structure](../packages/titlemcp/docs/JURISDICTION_STRUCTURE.md)
- [Ohio auditor expansion roadmap](OHIO_AUDITOR_EXPANSION.md)
- [Publishing](../packages/titlemcp/docs/PUBLISHING.md)

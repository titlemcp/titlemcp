## What this changes

<!-- One or two sentences. What behaviour is different after this than before. -->

## Why

<!--
The problem, not the solution. If it fixes an issue, link it. If it changes what
a tool returns, say what a caller relying on the old shape will see.
-->

## How it was verified

<!--
Paste the commands and their output. "Tests pass" on its own is not verification
a reviewer can check.

    ruff check .
    ruff format --check .
    python -m unittest discover -s packages/titlemcp/tests

If the change affects what a tool or service returns, show a before and after of
the record, using fictitious parcels, names and recordings.
-->

```
```

## Checklist

- [ ] `ruff check .` and `ruff format --check .` are clean.
- [ ] `python -m unittest discover -s packages/titlemcp/tests` passes.
- [ ] New or changed behaviour has a test, and the test would fail without the change.
- [ ] Domain records keep their `schema_version`, `record_type`, `source` block and provenance, per AGENTS.md.
- [ ] No real parcels, names, recordings or file numbers anywhere in the diff. This repository is public.
- [ ] Nothing here makes a legal, underwriting or recording judgement on a reviewer's behalf.

"""Each state's deadline for releasing a paid-off mortgage, as its statute sets it.

The deadlines are data, in ``data/release_deadlines.json``: one entry per
state, each read from the statute's official text and cited with its URL. A
state that isn't listed has no deadline on file, and release tracking says so
rather than guess. Not listed:
- California, Georgia, Tennessee and Mississippi, until their current text is
  read on an official site;
- Idaho, which says only "immediately" on demand;
- New Mexico, which sets no time limit.
"""

from __future__ import annotations

import json
from pathlib import Path

from title_mcp.domain.release_tracking import ReleaseDeadline

TABLE = Path(__file__).with_name("data") / "release_deadlines.json"

RELEASE_DEADLINES: dict[str, ReleaseDeadline] = {
    deadline.state: deadline
    for deadline in map(ReleaseDeadline.model_validate, json.loads(TABLE.read_text("utf-8")))
}


def deadline_for(state: str | None) -> ReleaseDeadline | None:
    return RELEASE_DEADLINES.get((state or "").upper())

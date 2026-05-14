from __future__ import annotations

import contextlib
import contextvars
import time
from collections.abc import Iterator
from uuid import uuid4

from title_mcp.observability.logging import get_logger

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def current_trace_id() -> str | None:
    return _trace_id.get()


@contextlib.contextmanager
def trace_span(name: str, **fields: object) -> Iterator[str]:
    trace_id = _trace_id.get() or uuid4().hex
    token = _trace_id.set(trace_id)
    logger = get_logger("title_mcp.trace")
    started = time.perf_counter()
    logger.info("span.start", extra={"_trace_id": trace_id, "span": name, **fields})
    try:
        yield trace_id
    except Exception:
        logger.exception("span.error", extra={"_trace_id": trace_id, "span": name, **fields})
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "span.end",
            extra={"_trace_id": trace_id, "span": name, "elapsed_ms": elapsed_ms, **fields},
        )
        _trace_id.reset(token)

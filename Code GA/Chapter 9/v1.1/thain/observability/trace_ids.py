from __future__ import annotations

import itertools
import uuid

# Process-scoped monotonic counter; reset on process restart
_TURN_COUNTER = itertools.count(1)


def new_run_id() -> str:
    return uuid.uuid4().hex


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_turn_id() -> int:
    return next(_TURN_COUNTER)

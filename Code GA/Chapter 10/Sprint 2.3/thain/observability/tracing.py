from __future__ import annotations

from pathlib import Path

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    ts: str
    type: str
    run_id: str
    trace_id: str
    turn_id: int
    data: dict[str, Any]


@dataclass(frozen=True)
class TraceContext:
    run_id: str
    trace_id: str
    turn_id: int
    started_at: str


@dataclass
class TraceRecorder:
    run_id: str
    trace_id: str
    turn_id: int
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    elapsed_ms: int | None = None
    _seq: int = 0
    _events: list[TraceEvent] = field(default_factory=list)

    def set_elapsed_ms(self, value: int) -> None:
        self.elapsed_ms = value

    def record(self, event_type: str, data: dict[str, Any]) -> None:
        self._seq += 1
        event = TraceEvent(
            seq=self._seq,
            ts=datetime.now(timezone.utc).isoformat(),
            type=event_type,
            run_id=self.run_id,
            trace_id=self.trace_id,
            turn_id=self.turn_id,
            data=data,
        )
        self._events.append(event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1",
            "context": {
                "run_id": self.run_id,
                "trace_id": self.trace_id,
                "turn_id": self.turn_id,
                "started_at": self.started_at,
                "elapsed_ms": self.elapsed_ms,
            },
            "events": [event.__dict__ for event in self._events],
        }

    def emit(self, path: str | None = None) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
        return payload

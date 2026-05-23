from __future__ import annotations

from pathlib import Path

from typing import Any, Protocol


class TraceSink(Protocol):
    def emit(self, trace: dict[str, Any]) -> str:
        ...


class FileTraceSink:
    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)

    def build_path(self, trace: dict[str, Any]) -> Path:
        context = trace.get("context", {})
        run_id = context.get("run_id", "run")
        trace_id = context.get("trace_id", "trace")
        turn_id = context.get("turn_id", "turn")
        target_dir = self._output_dir / f"run_{run_id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"trace_{trace_id}_turn_{turn_id}.json"

    def emit(self, trace: dict[str, Any]) -> str:
        path = self.build_path(trace)
        path.write_text(__import__("json").dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

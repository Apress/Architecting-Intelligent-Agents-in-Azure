from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_get(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    return mapping.get(key, default)


def render_trace_summary(trace: dict[str, Any]) -> str:
    context = _safe_get(trace, "context", {})
    schema_version = trace.get("schema_version", "unknown")
    trace_id = context.get("trace_id", "unknown")
    turn_id = context.get("turn_id", "unknown")
    elapsed_ms = context.get("elapsed_ms", "unknown")

    lines: list[str] = []
    lines.append(f"Trace {trace_id} (turn {turn_id}) schema={schema_version} elapsed_ms={elapsed_ms}")

    events = trace.get("events") or []
    policy_events = [e for e in events if e.get("type") == "policy.check"]
    tool_results = [e for e in events if e.get("type") == "tool.result"]
    response_ready = next((e for e in events if e.get("type") == "response.ready"), None)

    warns = [e for e in policy_events if _safe_get(e.get("data", {}), "decision") == "warn"]
    denies = [e for e in policy_events if _safe_get(e.get("data", {}), "decision") == "deny"]

    if denies or warns:
        lines.append("Policy decisions:")
        for evt in denies + warns:
            data = _safe_get(evt, "data", {})
            lines.append(
                f"- {data.get('decision')}: {data.get('tool_name')} rules={data.get('matched_rule_ids', [])}"
            )

    if tool_results:
        lines.append("Tool results:")
        for evt in tool_results:
            data = _safe_get(evt, "data", {})
            status = data.get("status")
            tool_name = data.get("tool_name")
            error_type = data.get("error_type")
            approved = _safe_get(_safe_get(data, "result", {}), "approved")
            suffix = f" error={error_type}" if error_type else ""
            if approved is not None:
                suffix += f" approved={approved}"
            lines.append(f"- {tool_name}: {status}{suffix}")

    if response_ready:
        data = _safe_get(response_ready, "data", {})
        lines.append(
            f"Response: category={data.get('category')} summary_len={data.get('summary_len')}, elapsed_ms={data.get('elapsed_ms')}"
        )

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Replay a Thain trace summary")
    parser.add_argument("trace_path", help="Path to trace JSON file")
    args = parser.parse_args()

    trace_path = Path(args.trace_path)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    print(render_trace_summary(trace))


if __name__ == "__main__":
    main()

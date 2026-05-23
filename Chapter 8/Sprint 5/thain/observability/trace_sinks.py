from __future__ import annotations

from pathlib import Path
import time

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


class AppInsightsTraceSink:
    def __init__(self, connection_string: str, service_name: str) -> None:
        self._connection_string = connection_string
        self._service_name = service_name
        self._tracer = None

    def _ensure_tracer(self) -> None:
        if self._tracer is not None:
            return
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        resource = Resource.create({"service.name": self._service_name})
        provider = TracerProvider(resource=resource)
        exporter = AzureMonitorTraceExporter(connection_string=self._connection_string)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("thain.tracing")

    def emit(self, trace: dict[str, Any]) -> str:
        self._ensure_tracer()
        context = trace.get("context", {})
        trace_id = context.get("trace_id", "")
        run_id = context.get("run_id", "")
        turn_id = context.get("turn_id", "")
        schema_version = trace.get("schema_version", "0.1")
        events = trace.get("events", [])
        event_count = len(events)
        elapsed_ms = context.get("elapsed_ms", 0)
        with self._tracer.start_as_current_span("thain.trace") as span:
            span.set_attribute("thain.trace_id", trace_id)
            span.set_attribute("thain.run_id", run_id)
            span.set_attribute("thain.turn_id", turn_id)
            span.set_attribute("thain.schema_version", schema_version)
            span.set_attribute("thain.event_count", event_count)
            span.set_attribute("thain.elapsed_ms", elapsed_ms)
            tool_names: list[str] = []
            retrieve_docs_statuses: list[str] = []
            for event in events:
                if event.get("type") != "tool.result":
                    continue
                data = event.get("data", {})
                if not isinstance(data, dict):
                    continue
                tool_name = data.get("tool_name")
                if tool_name:
                    tool_name = str(tool_name)
                    tool_names.append(tool_name)
                    if tool_name == "retrieve_docs" and data.get("status") is not None:
                        retrieve_docs_statuses.append(str(data.get("status")))
            if tool_names:
                unique_tools = sorted(set(tool_names))
                span.set_attribute("thain.tool.count", len(tool_names))
                span.set_attribute("thain.tool.names", ",".join(unique_tools))
                if "retrieve_docs" in unique_tools:
                    span.set_attribute("thain.tool.retrieve_docs", "true")
                    if retrieve_docs_statuses:
                        span.set_attribute(
                            "thain.tool.retrieve_docs_status",
                            ",".join(sorted(set(retrieve_docs_statuses))),
                        )
                else:
                    span.set_attribute("thain.tool.retrieve_docs", "false")
            for event in events:
                event_name = event.get("type", "event")
                event_attrs = {
                    "thain.event.seq": event.get("sequence"),
                    "thain.event.ts": event.get("timestamp"),
                }
                data = event.get("data", {})
                if isinstance(data, dict):
                    for key, value in data.items():
                        if value is None:
                            continue
                        if isinstance(value, (str, int, float, bool)):
                            event_attrs[f"thain.event.{key}"] = value
                span.add_event(event_name, event_attrs, time.time())
        return "appinsights"

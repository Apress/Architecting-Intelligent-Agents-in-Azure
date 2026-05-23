from __future__ import annotations

from pathlib import Path
import time
from datetime import datetime, timezone

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
            span.set_attribute("thain.latency.total_ms", elapsed_ms)
            tool_names: list[str] = []
            retrieve_docs_statuses: list[str] = []
            approval_statuses: list[str] = []
            approval_tools: list[str] = []
            feedback_scenarios: list[str] = []
            feedback_decisions: list[str] = []
            feedback_reasons: list[str] = []
            feedback_ratings: list[str] = []
            tool_durations: list[int] = []
            retrieve_docs_durations: list[int] = []
            llm_usage: dict[str, Any] = {}
            for event in events:
                event_type = event.get("type")
                data = event.get("data", {})
                if event_type == "tool.result" and isinstance(data, dict):
                    tool_name = data.get("tool_name")
                    if tool_name:
                        tool_name = str(tool_name)
                        tool_names.append(tool_name)
                        duration = data.get("duration_ms")
                        if duration is not None:
                            try:
                                duration_ms = int(duration)
                                tool_durations.append(duration_ms)
                                if tool_name == "retrieve_docs":
                                    retrieve_docs_durations.append(duration_ms)
                            except (TypeError, ValueError):
                                pass
                        if tool_name == "retrieve_docs" and data.get("status") is not None:
                            retrieve_docs_statuses.append(str(data.get("status")))
                if event_type in {"approval.request", "approval.decision"} and isinstance(data, dict):
                    status = data.get("status") or data.get("decision")
                    tool_name = data.get("tool_name")
                    if status:
                        approval_statuses.append(str(status))
                    if tool_name:
                        approval_tools.append(str(tool_name))
                if event_type == "feedback.submitted" and isinstance(data, dict):
                    scenario = data.get("scenario")
                    decision = data.get("decision")
                    reason = data.get("reason")
                    rating = data.get("rating")
                    if scenario:
                        feedback_scenarios.append(str(scenario))
                    if decision:
                        feedback_decisions.append(str(decision))
                    if reason:
                        feedback_reasons.append(str(reason))
                    if rating is not None:
                        feedback_ratings.append(str(rating))
                if event_type == "llm.usage" and isinstance(data, dict):
                    llm_usage = data
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
            if tool_durations:
                span.set_attribute("thain.latency.tool_ms", sum(tool_durations))
            if retrieve_docs_durations:
                span.set_attribute("thain.latency.retrieve_docs_ms", sum(retrieve_docs_durations))
            if approval_statuses:
                span.set_attribute("thain.approval.count", len(approval_statuses))
                span.set_attribute("thain.approval.statuses", ",".join(sorted(set(approval_statuses))))
                if approval_tools:
                    span.set_attribute("thain.approval.tools", ",".join(sorted(set(approval_tools))))
            if feedback_scenarios or feedback_decisions or feedback_reasons or feedback_ratings:
                span.set_attribute("thain.feedback.submitted", "true")
                if feedback_scenarios:
                    span.set_attribute("thain.feedback.scenario", ",".join(sorted(set(feedback_scenarios))))
                if feedback_decisions:
                    span.set_attribute("thain.feedback.decision", ",".join(sorted(set(feedback_decisions))))
                if feedback_reasons:
                    span.set_attribute("thain.feedback.reason", ",".join(sorted(set(feedback_reasons))))
                if feedback_ratings:
                    unique_ratings = sorted(set(feedback_ratings))
                    if len(unique_ratings) == 1:
                        try:
                            span.set_attribute("thain.feedback.rating", int(unique_ratings[0]))
                        except ValueError:
                            span.set_attribute("thain.feedback.rating", unique_ratings[0])
                    else:
                        span.set_attribute("thain.feedback.rating", ",".join(unique_ratings))
            if llm_usage:
                model_name = llm_usage.get("model")
                if model_name:
                    span.set_attribute("thain.model.name", str(model_name))
                model_profile = llm_usage.get("model_profile")
                if model_profile:
                    span.set_attribute("thain.model.profile", str(model_profile))
                usage_source = llm_usage.get("usage_source")
                if usage_source:
                    span.set_attribute("thain.tokens.source", str(usage_source))
                cache_hit = llm_usage.get("cache_hit")
                if cache_hit is not None:
                    if isinstance(cache_hit, bool):
                        span.set_attribute("thain.cache.hit", "true" if cache_hit else "false")
                    else:
                        span.set_attribute("thain.cache.hit", str(cache_hit).lower())
                prompt_tokens = llm_usage.get("prompt_tokens")
                completion_tokens = llm_usage.get("completion_tokens")
                total_tokens = llm_usage.get("total_tokens")
                if prompt_tokens is not None:
                    try:
                        span.set_attribute("thain.tokens.prompt", int(prompt_tokens))
                    except (TypeError, ValueError):
                        span.set_attribute("thain.tokens.prompt", prompt_tokens)
                if completion_tokens is not None:
                    try:
                        span.set_attribute("thain.tokens.completion", int(completion_tokens))
                    except (TypeError, ValueError):
                        span.set_attribute("thain.tokens.completion", completion_tokens)
                if total_tokens is not None:
                    try:
                        span.set_attribute("thain.tokens.total", int(total_tokens))
                    except (TypeError, ValueError):
                        span.set_attribute("thain.tokens.total", total_tokens)
                cost_estimate = llm_usage.get("cost_estimate_usd")
                if cost_estimate is not None:
                    try:
                        span.set_attribute("thain.cost.estimate_usd", float(cost_estimate))
                    except (TypeError, ValueError):
                        span.set_attribute("thain.cost.estimate_usd", cost_estimate)
                    span.set_attribute("thain.cost.estimate_available", "true")
                else:
                    span.set_attribute("thain.cost.estimate_available", "false")
            for event in events:
                event_name = event.get("type", "event")
                event_time_ns = None
                event_ts = event.get("ts")
                if event_ts:
                    try:
                        event_dt = datetime.fromisoformat(str(event_ts).replace("Z", "+00:00"))
                        event_time_ns = int(event_dt.timestamp() * 1_000_000_000)
                    except ValueError:
                        event_time_ns = None
                event_attrs = {
                    "thain.event.seq": event.get("seq"),
                    "thain.event.ts": event_ts,
                }
                data = event.get("data", {})
                if isinstance(data, dict):
                    for key, value in data.items():
                        if value is None:
                            continue
                        if isinstance(value, (str, int, float, bool)):
                            event_attrs[f"thain.event.{key}"] = value
                if event_time_ns:
                    span.add_event(event_name, event_attrs, event_time_ns)
                else:
                    span.add_event(event_name, event_attrs)
        return "appinsights"

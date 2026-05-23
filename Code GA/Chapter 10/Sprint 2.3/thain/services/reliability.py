from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")
EventCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class ReliabilityConfig:
    enabled: bool
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int
    jitter_ratio: float
    cooldown_seconds: int
    failure_threshold: int
    timeout_openai_ms: int
    timeout_search_ms: int
    timeout_cosmos_ms: int
    chaos_openai_failure: bool
    chaos_search_failure: bool
    chaos_cosmos_failure: bool


@dataclass
class _DependencyState:
    consecutive_failures: int = 0
    suppressed_until_monotonic: float = 0.0


class DependencySuppressed(RuntimeError):
    def __init__(self, dependency: str, operation: str, remaining_seconds: float) -> None:
        super().__init__(
            f"Dependency '{dependency}' temporarily suppressed for operation '{operation}' "
            f"({remaining_seconds:.1f}s remaining)."
        )
        self.dependency = dependency
        self.operation = operation
        self.remaining_seconds = remaining_seconds


class DependencyFailure(RuntimeError):
    def __init__(
        self,
        dependency: str,
        operation: str,
        error_type: str,
        attempts: int,
        retries: int,
        suppressed: bool,
        message: str,
    ) -> None:
        super().__init__(
            f"Dependency '{dependency}' failed for operation '{operation}' after {attempts} attempt(s): {message}"
        )
        self.dependency = dependency
        self.operation = operation
        self.error_type = error_type
        self.attempts = attempts
        self.retries = retries
        self.suppressed = suppressed


_DEPENDENCY_STATE: dict[str, _DependencyState] = {}
_STATE_LOCK = asyncio.Lock()
_EVENT_CALLBACK_CTX: ContextVar[EventCallback | None] = ContextVar(
    "thain_reliability_event_callback",
    default=None,
)


@contextmanager
def reliability_event_scope(callback: EventCallback | None):
    token: Token[EventCallback | None] | None = None
    if callback:
        token = _EVENT_CALLBACK_CTX.set(callback)
    try:
        yield
    finally:
        if token is not None:
            _EVENT_CALLBACK_CTX.reset(token)


def set_reliability_event_callback(callback: EventCallback | None) -> Token[EventCallback | None] | None:
    if not callback:
        return None
    return _EVENT_CALLBACK_CTX.set(callback)


def reset_reliability_event_callback(token: Token[EventCallback | None] | None) -> None:
    if token is not None:
        _EVENT_CALLBACK_CTX.reset(token)


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        return max(int(raw), minimum)
    except ValueError:
        return max(default, minimum)


def _parse_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        return max(float(raw), minimum)
    except ValueError:
        return max(default, minimum)


def load_reliability_config() -> ReliabilityConfig:
    return ReliabilityConfig(
        enabled=_parse_bool_env("THAIN_ENABLE_RELIABILITY", True),
        max_attempts=_parse_int_env("THAIN_RETRY_MAX_ATTEMPTS", 3, minimum=1),
        base_delay_ms=_parse_int_env("THAIN_RETRY_BASE_DELAY_MS", 250, minimum=10),
        max_delay_ms=_parse_int_env("THAIN_RETRY_MAX_DELAY_MS", 2000, minimum=50),
        jitter_ratio=_parse_float_env("THAIN_RETRY_JITTER_RATIO", 0.2, minimum=0.0),
        cooldown_seconds=_parse_int_env("THAIN_DEPENDENCY_COOLDOWN_SECONDS", 30, minimum=1),
        failure_threshold=_parse_int_env("THAIN_DEPENDENCY_FAILURE_THRESHOLD", 2, minimum=1),
        timeout_openai_ms=_parse_int_env("THAIN_TIMEOUT_OPENAI_MS", 45000, minimum=1000),
        timeout_search_ms=_parse_int_env("THAIN_TIMEOUT_SEARCH_MS", 8000, minimum=500),
        timeout_cosmos_ms=_parse_int_env("THAIN_TIMEOUT_COSMOS_MS", 5000, minimum=500),
        chaos_openai_failure=_parse_bool_env("THAIN_CHAOS_SIMULATE_OPENAI_FAILURE", False),
        chaos_search_failure=_parse_bool_env("THAIN_CHAOS_SIMULATE_SEARCH_FAILURE", False),
        chaos_cosmos_failure=_parse_bool_env("THAIN_CHAOS_SIMULATE_COSMOS_FAILURE", False),
    )


def timeout_ms_for_dependency(dependency: str, config: ReliabilityConfig | None = None) -> int:
    cfg = config or load_reliability_config()
    dep = dependency.strip().lower()
    if dep == "openai":
        return cfg.timeout_openai_ms
    if dep == "search":
        return cfg.timeout_search_ms
    return cfg.timeout_cosmos_ms


def _emit_event(
    callback: EventCallback | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    sink = callback or _EVENT_CALLBACK_CTX.get()
    if sink:
        sink(event_type, payload)


def _is_chaos_enabled(config: ReliabilityConfig, dependency: str) -> bool:
    dep = dependency.strip().lower()
    if dep == "openai":
        return config.chaos_openai_failure
    if dep == "search":
        return config.chaos_search_failure
    if dep == "cosmos":
        return config.chaos_cosmos_failure
    return False


def _compute_delay_ms(config: ReliabilityConfig, attempt: int) -> int:
    base = config.base_delay_ms * (2 ** max(attempt - 1, 0))
    bounded = min(base, config.max_delay_ms)
    if config.jitter_ratio <= 0:
        return bounded
    jitter = bounded * config.jitter_ratio
    adjusted = bounded + random.uniform(-jitter, jitter)
    return max(1, int(round(adjusted)))


def _state_for_dependency(dependency: str) -> _DependencyState:
    dep = dependency.strip().lower()
    state = _DEPENDENCY_STATE.get(dep)
    if state is None:
        state = _DependencyState()
        _DEPENDENCY_STATE[dep] = state
    return state


async def _suppression_remaining_seconds(dependency: str) -> float:
    now = time.monotonic()
    async with _STATE_LOCK:
        state = _state_for_dependency(dependency)
        remaining = state.suppressed_until_monotonic - now
        if remaining <= 0:
            if state.suppressed_until_monotonic > 0:
                state.suppressed_until_monotonic = 0.0
            return 0.0
        return remaining


async def _mark_success(dependency: str) -> None:
    async with _STATE_LOCK:
        state = _state_for_dependency(dependency)
        state.consecutive_failures = 0
        state.suppressed_until_monotonic = 0.0


async def _mark_terminal_failure(
    dependency: str,
    config: ReliabilityConfig,
) -> tuple[bool, int]:
    now = time.monotonic()
    async with _STATE_LOCK:
        state = _state_for_dependency(dependency)
        state.consecutive_failures += 1
        suppressed = state.consecutive_failures >= config.failure_threshold
        if suppressed:
            state.suppressed_until_monotonic = now + config.cooldown_seconds
        return suppressed, state.consecutive_failures


async def _run_with_timeout(
    operation: Callable[[], Awaitable[T]],
    timeout_ms: int | None,
) -> T:
    if not timeout_ms or timeout_ms <= 0:
        return await operation()
    return await asyncio.wait_for(operation(), timeout=timeout_ms / 1000.0)


async def execute_dependency_call(
    dependency: str,
    operation_name: str,
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_ms: int | None = None,
    passthrough_exceptions: tuple[type[BaseException], ...] = (),
    on_event: EventCallback | None = None,
) -> T:
    config = load_reliability_config()
    resolved_timeout_ms = timeout_ms or timeout_ms_for_dependency(dependency, config=config)
    dep = dependency.strip().lower() or "unknown"
    op_name = operation_name.strip() or "operation"

    if _is_chaos_enabled(config, dep):
        _emit_event(
            on_event,
            "dependency.failure",
            {
                "dependency": dep,
                "operation": op_name,
                "attempt": 1,
                "max_attempts": 1,
                "error_type": "ChaosInjectedFailure",
                "retryable": "false",
            },
        )
        raise DependencyFailure(
            dependency=dep,
            operation=op_name,
            error_type="ChaosInjectedFailure",
            attempts=1,
            retries=0,
            suppressed=False,
            message="Injected failure via chaos flag.",
        )

    if not config.enabled:
        return await _run_with_timeout(operation, resolved_timeout_ms)

    remaining = await _suppression_remaining_seconds(dep)
    if remaining > 0:
        _emit_event(
            on_event,
            "dependency.suppressed",
            {
                "dependency": dep,
                "operation": op_name,
                "cooldown_seconds": round(remaining, 3),
                "reason": "cooldown_active",
            },
        )
        raise DependencySuppressed(dep, op_name, remaining)

    attempts = max(config.max_attempts, 1)
    retries = 0
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            result = await _run_with_timeout(operation, resolved_timeout_ms)
            await _mark_success(dep)
            return result
        except Exception as exc:  # noqa: BLE001
            if passthrough_exceptions and isinstance(exc, passthrough_exceptions):
                await _mark_success(dep)
                raise
            last_exc = exc
            error_type = type(exc).__name__
            retryable = attempt < attempts
            _emit_event(
                on_event,
                "dependency.failure",
                {
                    "dependency": dep,
                    "operation": op_name,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "error_type": error_type,
                    "retryable": "true" if retryable else "false",
                },
            )
            if retryable:
                retries += 1
                delay_ms = _compute_delay_ms(config, retries)
                _emit_event(
                    on_event,
                    "dependency.retry",
                    {
                        "dependency": dep,
                        "operation": op_name,
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": attempts,
                        "delay_ms": delay_ms,
                    },
                )
                await asyncio.sleep(delay_ms / 1000.0)
                continue

            suppressed, consecutive_failures = await _mark_terminal_failure(dep, config)
            if suppressed:
                _emit_event(
                    on_event,
                    "dependency.suppressed",
                    {
                        "dependency": dep,
                        "operation": op_name,
                        "cooldown_seconds": config.cooldown_seconds,
                        "consecutive_failures": consecutive_failures,
                        "reason": "failure_threshold_reached",
                    },
                )

            raise DependencyFailure(
                dependency=dep,
                operation=op_name,
                error_type=error_type,
                attempts=attempts,
                retries=retries,
                suppressed=suppressed,
                message=str(exc),
            ) from exc

    # Unreachable guard
    if last_exc is None:
        last_exc = RuntimeError("Unknown dependency failure")
    raise DependencyFailure(
        dependency=dep,
        operation=op_name,
        error_type=type(last_exc).__name__,
        attempts=attempts,
        retries=retries,
        suppressed=False,
        message=str(last_exc),
    ) from last_exc

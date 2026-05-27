#!/usr/bin/env python3
"""Concurrent load/stress tester for the FastAPI RAG chat API.

This script exercises the running ``/chat`` endpoint with concurrent threads,
measures latency distribution and error rate, and optionally validates the
``/chat/stream`` SSE endpoint.

Requirements satisfied:
  - stdlib only (plus urllib, threading, time, statistics)
  - 100 concurrent users by default
  - repeated pricing, streaming, cache-hit, and governance recovery stress
  - p50/p95/p99, cache-hit ratio, recovery frequency, streaming completion rate
  - unique ``session_id`` per concurrent request unless cache scenario needs reuse
  - 60s timeout per request
  - graceful error handling (no tracebacks)
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence


DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 60.0
STREAMING_SAMPLES = 5

QUESTION_IDENTITY = "Kdo jste?"
QUESTION_OVERVIEW = "Co je eKonto?"
QUESTION_PRICING = "Kolik stojí vedení účtu?"
QUESTION_RECOVERY = "Najdi aktuální informace k poplatkům za běžný účet, ne historický sazebník."


@dataclass(frozen=True)
class ScenarioSpec:
    """Definition of a concurrent request scenario."""

    name: str
    path: str
    questions: tuple[str, ...]


@dataclass
class RequestOutcome:
    """Result of a single request."""

    latency_ms: float
    ok: bool
    status_code: int | None = None
    error: str | None = None
    first_token_ms: float | None = None
    total_ms: float | None = None
    cache_hit: bool | None = None
    recovery_used: bool = False
    streaming_completed: bool | None = None


@dataclass
class ScenarioResult:
    """Aggregated metrics for a scenario."""

    name: str
    requested: int
    outcomes: list[RequestOutcome] = field(default_factory=list)
    wall_time_seconds: float = 0.0

    @property
    def errors(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.ok)

    @property
    def latencies_ms(self) -> list[float]:
        return [outcome.latency_ms for outcome in self.outcomes]

    @property
    def throughput_rps(self) -> float:
        if self.wall_time_seconds <= 0:
            return 0.0
        return self.requested / self.wall_time_seconds


def build_request(api_url: str, path: str, payload: dict[str, Any], *, accept: str) -> urllib.request.Request:
    """Create a JSON POST request."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        url=f"{api_url.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={
            "Accept": accept,
            "Content-Type": "application/json",
            "User-Agent": "rag-banking-load-test/1.0",
        },
    )


def make_session_id(i: int) -> str:
    """Generate a unique session id per request."""

    return f"load-{time.time_ns()}-{i}"


def percentile(values: Sequence[float], percent: float) -> float:
    """Compute a percentile using linear interpolation."""

    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (percent / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    low_value = ordered[lower]
    high_value = ordered[upper]
    return float(low_value + (high_value - low_value) * (rank - lower))


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace") if body else ""


def _read_json_response(response: Any) -> tuple[int, dict[str, Any] | None, str]:
    """Read a JSON HTTP response and return (status, payload, raw_text)."""

    status_code = int(getattr(response, "status", 200))
    raw_text = _decode_body(response.read())
    if not raw_text:
        return status_code, None, raw_text
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return status_code, None, raw_text
    return status_code, payload if isinstance(payload, dict) else None, raw_text


def _debug_rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    debug = payload.get("retrieval_debug")
    if isinstance(debug, list):
        return [row for row in debug if isinstance(row, dict)]
    if isinstance(debug, dict):
        return [debug]
    return []


def _payload_cache_hit(payload: dict[str, Any] | None) -> bool | None:
    for row in _debug_rows(payload):
        if "cache_hit" in row:
            return bool(row.get("cache_hit"))
    return bool(payload.get("cache_hit")) if payload and "cache_hit" in payload else None


def _payload_recovery_used(payload: dict[str, Any] | None) -> bool:
    return any(row.get("recovery_pass_used") is True for row in _debug_rows(payload))


def run_chat_request(api_url: str, path: str, question: str, index: int, timeout_seconds: float) -> RequestOutcome:
    """Execute one /chat request and capture latency/error information."""

    session_id = make_session_id(index)
    request = build_request(
        api_url,
        path,
        {"question": question, "session_id": session_id},
        accept="application/json",
    )
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code, payload, raw_text = _read_json_response(response)
            latency_ms = (time.perf_counter() - start) * 1000.0

            if status_code != 200:
                return RequestOutcome(
                    latency_ms=latency_ms,
                    ok=False,
                    status_code=status_code,
                    error=f"HTTP {status_code}: {raw_text[:300]}",
                )

            if payload is None:
                return RequestOutcome(
                    latency_ms=latency_ms,
                    ok=False,
                    status_code=status_code,
                    error="invalid JSON response",
                )

            if payload.get("error"):
                return RequestOutcome(
                    latency_ms=latency_ms,
                    ok=False,
                    status_code=status_code,
                    error=str(payload.get("error")),
                )

            return RequestOutcome(
                latency_ms=latency_ms,
                ok=True,
                status_code=status_code,
                cache_hit=_payload_cache_hit(payload),
                recovery_used=_payload_recovery_used(payload),
            )
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        try:
            body = _decode_body(exc.read())
        except Exception:
            body = ""
        detail = body or exc.reason or "HTTP error"
        return RequestOutcome(latency_ms=latency_ms, ok=False, status_code=int(exc.code), error=str(detail))
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error=f"connection error: {exc.reason}")
    except TimeoutError:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error="timeout")
    except Exception as exc:  # pragma: no cover - guardrail for production script
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error=f"unexpected error: {exc}")


def _parse_sse_messages(response: Any, timeout_seconds: float) -> tuple[float | None, float | None, bool, str | None]:
    """Parse SSE stream and return first-token latency, total latency and error state."""

    start = time.perf_counter()
    deadline = start + timeout_seconds
    buffer = ""
    current_event: str | None = None
    current_data: list[str] = []
    first_token_ms: float | None = None
    saw_done = False
    error_text: str | None = None

    def flush_event() -> tuple[str | None, str]:
        nonlocal current_event, current_data
        event_name = (current_event or "message").strip() or "message"
        data = "\n".join(current_data)
        current_event = None
        current_data = []
        return event_name, data

    while True:
        if time.perf_counter() > deadline:
            return first_token_ms, (time.perf_counter() - start) * 1000.0, False, "timeout"

        chunk = response.read(1024)
        if not chunk:
            break

        buffer += chunk.decode("utf-8", errors="replace")
        while True:
            newline_index = buffer.find("\n")
            if newline_index < 0:
                break
            line = buffer[:newline_index]
            buffer = buffer[newline_index + 1 :]

            if line.endswith("\r"):
                line = line[:-1]

            if not line:
                if current_event is None and not current_data:
                    continue
                event_name, data_text = flush_event()
                if event_name == "token" and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000.0
                elif event_name == "done":
                    saw_done = True
                elif event_name == "error":
                    error_text = data_text or "stream error"
                continue

            if line.startswith(":"):
                continue

            if ":" in line:
                field_name, value = line.split(":", 1)
                if value.startswith(" "):
                    value = value[1:]
            else:
                field_name, value = line, ""

            if field_name == "event":
                current_event = value
            elif field_name == "data":
                current_data.append(value)

    if buffer:
        # Process trailing partial event safely.
        line = buffer.rstrip("\r")
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].lstrip(" ")
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].lstrip(" "))

    if current_event is not None or current_data:
        event_name, data_text = flush_event()
        if event_name == "token" and first_token_ms is None:
            first_token_ms = (time.perf_counter() - start) * 1000.0
        elif event_name == "done":
            saw_done = True
        elif event_name == "error":
            error_text = data_text or "stream error"

    total_ms = (time.perf_counter() - start) * 1000.0
    ok = saw_done and error_text is None and first_token_ms is not None
    return first_token_ms, total_ms, ok, error_text


def run_stream_request(api_url: str, question: str, index: int, timeout_seconds: float) -> RequestOutcome:
    """Execute one /chat/stream request and capture token timing."""

    session_id = make_session_id(index)
    request = build_request(
        api_url,
        "/chat/stream",
        {"question": question, "session_id": session_id},
        accept="text/event-stream",
    )
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            first_token_ms, total_ms, ok, error_text = _parse_sse_messages(response, timeout_seconds)
            if total_ms == 0.0:
                total_ms = (time.perf_counter() - start) * 1000.0
            return RequestOutcome(
                latency_ms=total_ms,
                ok=ok,
                status_code=int(getattr(response, "status", 200)),
                error=error_text,
                first_token_ms=first_token_ms,
                total_ms=total_ms,
                streaming_completed=ok,
            )
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        try:
            body = _decode_body(exc.read())
        except Exception:
            body = ""
        detail = body or exc.reason or "HTTP error"
        return RequestOutcome(latency_ms=latency_ms, ok=False, status_code=int(exc.code), error=str(detail))
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error=f"connection error: {exc.reason}")
    except TimeoutError:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error="timeout")
    except Exception as exc:  # pragma: no cover - guardrail for production script
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RequestOutcome(latency_ms=latency_ms, ok=False, error=f"unexpected error: {exc}")


def run_concurrent_scenario(
    *,
    name: str,
    api_url: str,
    path: str,
    questions: Sequence[str],
    timeout_seconds: float,
    stream: bool = False,
) -> ScenarioResult:
    """Run a concurrent scenario and collect outcomes."""

    total = len(questions)
    result = ScenarioResult(name=name, requested=total)
    outcomes: list[RequestOutcome | None] = [None] * total
    lock = threading.Lock()
    start_event = threading.Event()

    def worker(index: int, question: str) -> None:
        try:
            start_event.wait()
            if stream:
                outcome = run_stream_request(api_url, question, index, timeout_seconds)
            else:
                outcome = run_chat_request(api_url, path, question, index, timeout_seconds)
        except Exception as exc:  # pragma: no cover - extra guardrail
            outcome = RequestOutcome(latency_ms=0.0, ok=False, error=f"unexpected worker error: {exc}")

        with lock:
            outcomes[index] = outcome

    threads = [threading.Thread(target=worker, args=(idx, question), daemon=True) for idx, question in enumerate(questions)]
    for thread in threads:
        thread.start()

    t0 = time.perf_counter()
    start_event.set()

    for thread in threads:
        thread.join()
    result.wall_time_seconds = max(time.perf_counter() - t0, 0.0)
    result.outcomes = [outcome for outcome in outcomes if outcome is not None]
    return result


def warmup_server(api_url: str, timeout_seconds: float, count: int) -> None:
    """Send non-reused warmup requests so cache keys do not collide with tests."""

    for i in range(max(count, 0)):
        question = f"Warmup ping {i} {time.time_ns()}"
        _ = run_chat_request(api_url, "/chat", question, i, timeout_seconds)


def print_scenario(result: ScenarioResult, label: str | None = None) -> None:
    """Print a scenario in the required summary format."""

    name = label or result.name
    total = max(result.requested, 1)
    latencies = result.latencies_ms
    avg = statistics.mean(latencies) if latencies else 0.0
    p50 = percentile(latencies, 50) if latencies else 0.0
    p95 = percentile(latencies, 95) if latencies else 0.0
    p99 = percentile(latencies, 99) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0
    errors = result.errors
    error_rate = (errors / total) * 100.0
    cache_known = [outcome.cache_hit for outcome in result.outcomes if outcome.cache_hit is not None]
    cache_hit_ratio = (sum(1 for value in cache_known if value) / len(cache_known)) if cache_known else None
    recovery_frequency = sum(1 for outcome in result.outcomes if outcome.recovery_used) / total

    print(f"{name}:")
    print(f"  Requests/sec:  {result.throughput_rps:.1f}")
    print(f"  Avg latency:   {avg:.1f} ms")
    print(f"  P50:           {p50:.1f} ms")
    print(f"  P95:           {p95:.1f} ms")
    print(f"  P99:           {p99:.1f} ms")
    print(f"  Cache hit ratio:{' n/a' if cache_hit_ratio is None else f' {cache_hit_ratio:.1%}'}")
    print(f"  Recovery freq: {recovery_frequency:.1%}")
    print(f"  Errors:        {errors}/{total} ({error_rate:.1f}%)")
    print(f"  Min/Max:       {min_latency:.1f} / {max_latency:.1f} ms")
    print()


def print_streaming_summary(result: ScenarioResult) -> None:
    """Print streaming metrics."""

    first_tokens = [outcome.first_token_ms for outcome in result.outcomes if outcome.first_token_ms is not None]
    totals = [outcome.total_ms for outcome in result.outcomes if outcome.total_ms is not None]
    avg_first = statistics.mean(first_tokens) if first_tokens else 0.0
    avg_total = statistics.mean(totals) if totals else 0.0
    total = max(result.requested, 1)
    errors = result.errors
    error_rate = (errors / total) * 100.0
    completion_rate = sum(1 for outcome in result.outcomes if outcome.streaming_completed) / total

    print("Streaming:")
    print(f"  Avg first token: {avg_first:.1f} ms")
    print(f"  Avg total:       {avg_total:.1f} ms")
    print(f"  Completion rate: {completion_rate:.1%}")
    print(f"  Errors:          {errors}/{total} ({error_rate:.1f}%)")
    print()


def build_scenarios(users: int) -> tuple[ScenarioSpec, ...]:
    """Return the benchmark scenarios."""

    identity = (QUESTION_IDENTITY,) * users
    overview = (QUESTION_OVERVIEW,) * users
    pricing = (QUESTION_PRICING,) * users
    recovery = (QUESTION_RECOVERY,) * users
    mixed = (QUESTION_IDENTITY, QUESTION_OVERVIEW, QUESTION_PRICING, QUESTION_RECOVERY) * max(1, users // 4)
    return (
        ScenarioSpec(name=f"Identity ({users} concurrent users)", path="/chat", questions=identity),
        ScenarioSpec(name=f"Overview ({users} concurrent users)", path="/chat", questions=overview),
        ScenarioSpec(name=f"Repeated pricing ({users} concurrent users)", path="/chat", questions=pricing),
        ScenarioSpec(name=f"Governance recovery stress ({users} concurrent users)", path="/chat", questions=recovery),
        ScenarioSpec(name=f"Mixed ({len(mixed)} concurrent users)", path="/chat", questions=mixed),
    )


def main() -> int:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Concurrent load/stress test for FastAPI /chat endpoint.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Base API URL (default: http://localhost:8000)")
    parser.add_argument("--skip-stream", action="store_true", help="Skip the /chat/stream workload")
    parser.add_argument("--warmup-requests", type=int, default=5, help="Number of warmup requests before testing")
    parser.add_argument("--users", type=int, default=100, help="Concurrent users per scenario (default: 100)")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    try:
        print("Warming up server...")
        warmup_server(api_url, timeout_seconds, args.warmup_requests)
        print("Warmup complete. Running load test...\n")

        cold_identity = run_concurrent_scenario(
            name="Cache cold (same 20 identity, uncached)",
            api_url=api_url,
            path="/chat",
            questions=(QUESTION_IDENTITY,) * 20,
            timeout_seconds=timeout_seconds,
            stream=False,
        )

        warm_identity = run_concurrent_scenario(
            name="Cache warm (same 20 identity, cached)",
            api_url=api_url,
            path="/chat",
            questions=(QUESTION_IDENTITY,) * 20,
            timeout_seconds=timeout_seconds,
            stream=False,
        )

        results: list[tuple[str, ScenarioResult]] = []
        for scenario in build_scenarios(max(1, args.users)):
            scenario_result = run_concurrent_scenario(
                name=scenario.name,
                api_url=api_url,
                path=scenario.path,
                questions=scenario.questions,
                timeout_seconds=timeout_seconds,
                stream=False,
            )
            results.append((scenario.name, scenario_result))

        streaming_result: ScenarioResult | None = None
        if not args.skip_stream:
            streaming_questions = (QUESTION_PRICING,) * max(STREAMING_SAMPLES, min(args.users, 20))
            streaming_result = run_concurrent_scenario(
                name=f"Streaming ({STREAMING_SAMPLES} concurrency)",
                api_url=api_url,
                path="/chat/stream",
                questions=streaming_questions,
                timeout_seconds=timeout_seconds,
                stream=True,
            )

        print("========================================")
        print("LOAD TEST SUMMARY")
        print("========================================")
        for _, scenario_result in results:
            print_scenario(scenario_result)
        print_scenario(cold_identity)
        print_scenario(warm_identity)

        if streaming_result is not None:
            print_streaming_summary(streaming_result)
        else:
            print("Streaming: skipped (--skip-stream)")
            print()

        print("========================================")
        return 0
    except KeyboardInterrupt:
        print("Load test interrupted by user.")
        return 130
    except Exception as exc:  # pragma: no cover - final guardrail
        print(f"Load test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

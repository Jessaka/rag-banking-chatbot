#!/usr/bin/env python3
"""Profile FastAPI chat routes by timing route-specific queries.

The script targets a running backend and measures the `/chat` endpoint for
multiple query classes, then optionally measures `/chat/stream` first-token
latency for the same queries.

Only the Python standard library is used (including ``urllib``).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 60.0
READ_CHUNK_SIZE = 1024
SEPARATOR = "=" * 40


@dataclass(frozen=True)
class QueryCase:
    """A single profiling query."""

    question: str
    route_type: str


@dataclass
class QuerySample:
    """Collected metrics for one request."""

    question: str
    route_type: str
    total_latency_ms: float | None = None
    retrieval_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    formatting_latency_ms: float | None = None
    cache_check_ms: float | None = None
    answer_strategy: str | None = None
    confidence_bucket: str | None = None
    error: str | None = None


@dataclass
class RouteStats:
    """Aggregated metrics for a route type."""

    route_type: str
    samples: list[QuerySample] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for sample in self.samples if sample.error)

    @property
    def successful_samples(self) -> list[QuerySample]:
        return [sample for sample in self.samples if sample.error is None and sample.total_latency_ms is not None]


@dataclass
class StreamSample:
    """Streaming metrics for one request."""

    question: str
    route_type: str
    first_token_latency_ms: float | None = None
    total_stream_latency_ms: float | None = None
    error: str | None = None


@dataclass
class StreamStats:
    """Aggregated streaming metrics for a route type."""

    route_type: str
    samples: list[StreamSample] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for sample in self.samples if sample.error)

    @property
    def successful_samples(self) -> list[StreamSample]:
        return [sample for sample in self.samples if sample.error is None and sample.first_token_latency_ms is not None]


QUERY_CASES: tuple[QueryCase, ...] = (
    QueryCase("Kdo jste?", "identity"),
    QueryCase("Co umíš?", "identity"),
    QueryCase("Kdo tě vytvořil?", "identity"),
    QueryCase("Kolik stojí vedení účtu?", "pricing"),
    QueryCase("Jaký je poplatek za výběr z bankomatu?", "pricing"),
    QueryCase("Kolik stojí kreditní karta?", "pricing"),
    QueryCase("Co je eKonto?", "overview"),
    QueryCase("Co je RB klíč?", "overview"),
    QueryCase("Co je to kreditní karta?", "overview"),
    QueryCase("Jak založím účet?", "procedural"),
    QueryCase("Jak aktivuji kartu?", "procedural"),
    QueryCase("Jak podám reklamaci?", "procedural"),
    QueryCase("Jaké jsou výhody spoření?", "llm_generic"),
    QueryCase("Jak funguje investiční fond?", "llm_generic"),
)


def build_request(api_url: str, path: str, question: str, session_id: str) -> urllib.request.Request:
    """Build a JSON POST request for the chat endpoints."""

    payload = json.dumps({"question": question, "session_id": session_id}).encode("utf-8")
    return urllib.request.Request(
        url=f"{api_url.rstrip('/')}/{path.lstrip('/')}",
        data=payload,
        headers={
            "Accept": "application/json" if path == "chat" else "text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "profile-routes/1.0",
        },
        method="POST",
    )


def coerce_float(value: Any) -> float | None:
    """Convert a JSON field to float if possible."""

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentiles(values: list[float], percentile: float) -> float | None:
    """Return a linear-interpolated percentile."""

    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def mean_or_none(values: list[float]) -> float | None:
    """Return the arithmetic mean or ``None`` for empty input."""

    if not values:
        return None
    return statistics.fmean(values)


def parse_json_response(response: Any) -> dict[str, Any]:
    """Decode a JSON response body into a dictionary."""

    body = response.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def profile_chat_case(api_url: str, case: QueryCase, timeout_seconds: float) -> QuerySample:
    """Profile one `/chat` request."""

    sample = QuerySample(question=case.question, route_type=case.route_type)
    request = build_request(api_url, "chat", case.question, str(uuid.uuid4()))

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            if status_code != 200:
                sample.error = f"HTTP {status_code}"
                return sample

            data = parse_json_response(response)

        sample.total_latency_ms = coerce_float(data.get("processing_time_ms"))
        sample.retrieval_latency_ms = coerce_float(data.get("retrieval_latency_ms"))
        sample.llm_latency_ms = coerce_float(data.get("llm_latency_ms"))
        sample.formatting_latency_ms = coerce_float(data.get("formatting_latency_ms"))
        sample.cache_check_ms = coerce_float(data.get("cache_check_ms"))
        sample.answer_strategy = data.get("answer_strategy") if isinstance(data.get("answer_strategy"), str) else None
        sample.confidence_bucket = data.get("confidence_bucket") if isinstance(data.get("confidence_bucket"), str) else None

        if sample.total_latency_ms is None:
            sample.error = "missing processing_time_ms"
        return sample
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sample.error = f"HTTP {exc.code}: {body or exc.reason}"
    except urllib.error.URLError as exc:
        sample.error = f"connection error: {exc.reason}"
    except json.JSONDecodeError as exc:
        sample.error = f"invalid JSON response: {exc}"
    except TimeoutError as exc:
        sample.error = f"timeout: {exc}"
    except Exception as exc:  # pragma: no cover - defensive guardrail
        sample.error = f"unexpected error: {exc}"
    return sample


def iter_sse_messages(response: Any, timeout_seconds: float) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield parsed SSE messages as ``(event, data)`` tuples."""

    deadline = time.perf_counter() + timeout_seconds
    buffer = ""
    current_event = "message"
    current_data: list[str] = []

    def process_line(line: str) -> tuple[str, dict[str, Any]] | None:
        nonlocal current_event, current_data
        if line.endswith("\r"):
            line = line[:-1]
        if line == "":
            return flush()
        if line.startswith(":"):
            return None
        if ":" in line:
            field_name, value = line.split(":", 1)
            if value.startswith(" "):
                value = value[1:]
        else:
            field_name, value = line, ""

        if field_name == "event":
            current_event = value or "message"
        elif field_name == "data":
            current_data.append(value)
        return None

    def flush() -> tuple[str, dict[str, Any]] | None:
        nonlocal current_event, current_data
        if not current_data and current_event == "message":
            return None
        raw_data = "\n".join(current_data)
        payload: dict[str, Any]
        if raw_data:
            try:
                decoded = json.loads(raw_data)
                payload = decoded if isinstance(decoded, dict) else {"value": decoded}
            except json.JSONDecodeError:
                payload = {"raw": raw_data}
        else:
            payload = {}
        message = (current_event or "message", payload)
        current_event = "message"
        current_data = []
        return message

    while True:
        if time.perf_counter() > deadline:
            raise TimeoutError(f"stream timed out after {timeout_seconds:.1f}s")

        chunk = response.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")

        while True:
            newline_index = buffer.find("\n")
            if newline_index < 0:
                break
            line = buffer[:newline_index]
            buffer = buffer[newline_index + 1 :]
            message = process_line(line)
            if message is not None:
                yield message

    if buffer:
        message = process_line(buffer)
        if message is not None:
            yield message
    message = flush()
    if message is not None:
        yield message


def profile_stream_case(api_url: str, case: QueryCase, timeout_seconds: float) -> StreamSample:
    """Profile one `/chat/stream` request."""

    sample = StreamSample(question=case.question, route_type=case.route_type)
    request = build_request(api_url, "chat/stream", case.question, str(uuid.uuid4()))
    t0 = time.perf_counter()
    seen_done = False

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            if status_code != 200:
                sample.error = f"HTTP {status_code}"
                return sample

            for event, data in iter_sse_messages(response, timeout_seconds=timeout_seconds):
                if event == "token" and sample.first_token_latency_ms is None:
                    sample.first_token_latency_ms = (time.perf_counter() - t0) * 1000.0
                elif event == "done":
                    seen_done = True

        sample.total_stream_latency_ms = (time.perf_counter() - t0) * 1000.0
        if sample.first_token_latency_ms is None:
            sample.error = "missing token event"
        elif not seen_done:
            sample.error = "missing done event"
        return sample
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sample.error = f"HTTP {exc.code}: {body or exc.reason}"
    except urllib.error.URLError as exc:
        sample.error = f"connection error: {exc.reason}"
    except TimeoutError as exc:
        sample.error = f"timeout: {exc}"
    except Exception as exc:  # pragma: no cover - defensive guardrail
        sample.error = f"unexpected error: {exc}"
    return sample


def collect_route_stats(samples: list[QuerySample]) -> list[RouteStats]:
    """Group samples by route type."""

    grouped: dict[str, RouteStats] = {}
    for sample in samples:
        grouped.setdefault(sample.route_type, RouteStats(route_type=sample.route_type)).samples.append(sample)
    return [grouped[key] for key in sorted(grouped)]


def collect_stream_stats(samples: list[StreamSample]) -> list[StreamStats]:
    """Group streaming samples by route type."""

    grouped: dict[str, StreamStats] = {}
    for sample in samples:
        grouped.setdefault(sample.route_type, StreamStats(route_type=sample.route_type)).samples.append(sample)
    return [grouped[key] for key in sorted(grouped)]


def _format_value(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def print_report(route_stats: list[RouteStats], stream_stats: list[StreamStats] | None = None) -> None:
    """Print the profiling report."""

    print(SEPARATOR)
    print("ROUTE PROFILING REPORT")
    print(SEPARATOR)

    route_order = ["identity", "pricing", "overview", "procedural", "llm_generic"]
    ordered = {stats.route_type: stats for stats in route_stats}
    for route_type in route_order:
        stats = ordered.get(route_type)
        if stats is None:
            continue
        successful = stats.successful_samples
        latencies = [sample.total_latency_ms for sample in successful if sample.total_latency_ms is not None]
        retrieval = [sample.retrieval_latency_ms for sample in successful if sample.retrieval_latency_ms is not None]
        llm = [sample.llm_latency_ms for sample in successful if sample.llm_latency_ms is not None]
        formatting = [sample.formatting_latency_ms for sample in successful if sample.formatting_latency_ms is not None]
        cache_check = [sample.cache_check_ms for sample in successful if sample.cache_check_ms is not None]

        label = "LLM/generic" if route_type == "llm_generic" else route_type
        suffix = f" ({len(stats.samples)} queries"
        if stats.error_count:
            suffix += f", {stats.error_count} errors"
        suffix += ")"
        print(f"{label}{suffix}:")
        print(f"  avg_latency_ms:      {_format_value(mean_or_none(latencies))}")
        print(f"  retrieval_ms:        {_format_value(mean_or_none(retrieval))}")
        print(f"  llm_ms:              {_format_value(mean_or_none(llm))}")
        print(f"  formatting_ms:       {_format_value(mean_or_none(formatting))}")
        print(f"  cache_check_ms:      {_format_value(mean_or_none(cache_check))}")
        print(f"  p50:                 {_format_value(percentiles(latencies, 0.50))}")
        print(f"  p95:                 {_format_value(percentiles(latencies, 0.95))}")
        print()

    print(SEPARATOR)
    print("TOP 5 SLOWEST ROUTES")
    print(SEPARATOR)
    ranked = []
    for stats in route_stats:
        successful = stats.successful_samples
        latencies = [sample.total_latency_ms for sample in successful if sample.total_latency_ms is not None]
        avg = mean_or_none(latencies)
        if avg is None:
            continue
        ranked.append((avg, stats.route_type, len(stats.samples)))
    ranked.sort(reverse=True)

    for index, (avg_latency, route_type, count) in enumerate(ranked[:5], start=1):
        label = "LLM/generic" if route_type == "llm_generic" else route_type
        print(f"{index}. {label:<13} avg {avg_latency:.1f}ms ({count} queries)")
    print(SEPARATOR)

    if stream_stats is None:
        return

    print()
    print(SEPARATOR)
    print("STREAMING PROFILE (/chat/stream)")
    print(SEPARATOR)
    for route_type in route_order:
        stats = next((item for item in stream_stats if item.route_type == route_type), None)
        if stats is None:
            continue
        successful = stats.successful_samples
        first_token = [sample.first_token_latency_ms for sample in successful if sample.first_token_latency_ms is not None]
        total_stream = [sample.total_stream_latency_ms for sample in successful if sample.total_stream_latency_ms is not None]
        label = "LLM/generic" if route_type == "llm_generic" else route_type
        suffix = f" ({len(stats.samples)} queries"
        if stats.error_count:
            suffix += f", {stats.error_count} errors"
        suffix += ")"
        print(f"{label}{suffix}:")
        print(f"  avg_first_token_ms:  {_format_value(mean_or_none(first_token))}")
        print(f"  avg_total_stream_ms: {_format_value(mean_or_none(total_stream))}")
        print()


def main() -> int:
    """Run the route profiler."""

    parser = argparse.ArgumentParser(description="Profile FastAPI /chat routes.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Base URL of the running API.")
    parser.add_argument("--skip-stream", action="store_true", help="Skip /chat/stream profiling.")
    args = parser.parse_args()

    parsed_api_url = urllib.parse.urlparse(args.api_url)
    if parsed_api_url.scheme not in {"http", "https"}:
        print("error: --api-url must include a scheme, e.g. http://localhost:8000", file=sys.stderr)
        return 2

    chat_samples = [profile_chat_case(args.api_url, case, DEFAULT_TIMEOUT_SECONDS) for case in QUERY_CASES]
    route_stats = collect_route_stats(chat_samples)

    stream_stats = None
    if not args.skip_stream:
        stream_samples = [profile_stream_case(args.api_url, case, DEFAULT_TIMEOUT_SECONDS) for case in QUERY_CASES]
        stream_stats = collect_stream_stats(stream_samples)

    print_report(route_stats, stream_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

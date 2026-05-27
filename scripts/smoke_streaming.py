#!/usr/bin/env python3
"""Streaming SSE smoke test for the FastAPI ``/chat/stream`` endpoint."""

from __future__ import annotations

import argparse
import codecs
import json
import logging
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
READ_CHUNK_SIZE = 1024
SEPARATOR = "=" * 40
SUBSEPARATOR = "-" * 40

LOGGER = logging.getLogger("smoke_streaming")


@dataclass(frozen=True)
class QueryCase:
    question: str
    category: str
    expected_routes: frozenset[str]
    strict_route_match: bool = False


@dataclass
class SSEMessage:
    event: str
    data: dict[str, Any]
    raw_data: str = ""
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class QueryResult:
    case: QueryCase
    route: str | None = None
    cache_hit: bool | None = None
    events: list[str] = field(default_factory=list)
    token_count: int = 0
    first_token_latency_ms: float | None = None
    total_latency_ms: float | None = None
    done_payload: dict[str, Any] = field(default_factory=dict)
    error_payloads: list[dict[str, Any]] = field(default_factory=list)
    http_status: int | None = None
    failure_reasons: list[str] = field(default_factory=list)
    exception_text: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failure_reasons and not self.exception_text


TEST_CASES: tuple[QueryCase, ...] = (
    QueryCase("Kdo jste?", "deterministic", frozenset({"identity_direct"}), strict_route_match=True),
    QueryCase(
        "Kolik stojí vedení účtu?",
        "pricing",
        frozenset({
            "clarification_direct",
            "pricing_row_direct",
            "pricing_section_llm",
            "pricing_table_llm",
            "overview_fallback",
        }),
    ),
    QueryCase("Jak založím účet online?", "llm", frozenset({"generic_llm"}), strict_route_match=True),
    QueryCase(
        "Jak aktivuju kartu?",
        "soft guidance",
        frozenset({"procedural_flow_direct", "soft_guidance_direct"}),
    ),
    QueryCase("Kolik stojí osobní eKonto?", "graceful degradation", frozenset({"overview_fallback"}), strict_route_match=True),
)


def build_request(api_url: str, question: str, session_id: str) -> urllib.request.Request:
    payload = json.dumps({"question": question, "session_id": session_id}).encode("utf-8")
    return urllib.request.Request(
        url=f"{api_url.rstrip('/')}/chat/stream",
        data=payload,
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "smoke-streaming/1.0",
        },
        method="POST",
    )


def _decode_event_data(raw_data: str) -> dict[str, Any]:
    if not raw_data:
        return {}
    try:
        decoded = json.loads(raw_data)
    except json.JSONDecodeError:
        return {"raw": raw_data}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def iter_sse_messages(response: Any, timeout_seconds: float) -> Iterable[SSEMessage]:
    decoder = codecs.getincrementaldecoder("utf-8")()
    text_buffer = ""
    current_event: str | None = None
    current_data: list[str] = []
    current_fields: dict[str, str] = {}
    deadline = time.perf_counter() + timeout_seconds

    def flush_pending() -> SSEMessage | None:
        nonlocal current_event, current_data, current_fields
        if current_event is None and not current_data and not current_fields:
            return None
        raw_data = "\n".join(current_data)
        message = SSEMessage(
            event=(current_event or "message").strip() or "message",
            data=_decode_event_data(raw_data),
            raw_data=raw_data,
            fields=dict(current_fields),
        )
        current_event = None
        current_data = []
        current_fields = {}
        return message

    def process_line(line: str) -> SSEMessage | None:
        nonlocal current_event, current_data, current_fields
        if line.endswith("\r"):
            line = line[:-1]
        if line == "":
            return flush_pending()
        if line.startswith(":"):
            return None
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
        else:
            current_fields[field_name] = value
        return None

    while True:
        if time.perf_counter() > deadline:
            raise TimeoutError(f"stream timed out after {timeout_seconds:.1f}s")
        chunk = response.read(READ_CHUNK_SIZE)
        if not chunk:
            text_buffer += decoder.decode(b"", final=True)
            break
        text_buffer += decoder.decode(chunk)

        while True:
            newline_index = text_buffer.find("\n")
            if newline_index < 0:
                break
            line = text_buffer[:newline_index]
            text_buffer = text_buffer[newline_index + 1 :]
            message = process_line(line)
            if message is not None:
                yield message

    if text_buffer:
        message = process_line(text_buffer)
        if message is not None:
            yield message
    message = flush_pending()
    if message is not None:
        yield message


def run_stream_query(case: QueryCase, api_url: str, timeout_seconds: float, session_id: str | None = None) -> QueryResult:
    result = QueryResult(case=case)
    request = build_request(api_url=api_url, question=case.question, session_id=session_id or str(uuid.uuid4()))
    t0 = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result.http_status = int(getattr(response, "status", 200))
            for message in iter_sse_messages(response, timeout_seconds=timeout_seconds):
                result.events.append(message.event)
                if message.event == "start":
                    result.route = _coerce_str(message.data.get("answer_strategy"))
                    result.cache_hit = _coerce_bool(message.data.get("cache_hit"))
                elif message.event == "token":
                    result.token_count += 1
                    if result.first_token_latency_ms is None:
                        result.first_token_latency_ms = (time.perf_counter() - t0) * 1000.0
                elif message.event == "done":
                    result.done_payload = message.data
                elif message.event == "error":
                    result.error_payloads.append(message.data)

            result.total_latency_ms = (time.perf_counter() - t0) * 1000.0
    except urllib.error.HTTPError as exc:
        result.http_status = int(exc.code)
        body = exc.read().decode("utf-8", errors="replace")
        result.exception_text = f"HTTP {exc.code}: {body or exc.reason}"
        return result
    except urllib.error.URLError as exc:
        result.exception_text = f"Connection error: {exc.reason}"
        return result
    except TimeoutError as exc:
        result.exception_text = f"Timeout: {exc}"
        return result
    except Exception as exc:  # pragma: no cover - smoke script guardrail
        LOGGER.exception("Unexpected stream test error for query: %s", case.question)
        result.exception_text = f"Unexpected error: {exc}"
        return result

    validate_result(result)
    return result


def validate_result(result: QueryResult) -> None:
    events = result.events
    if result.http_status != 200:
        result.failure_reasons.append(f"unexpected HTTP status {result.http_status}")
    if not events:
        result.failure_reasons.append("no SSE events received")
        return
    if events[0] != "start":
        result.failure_reasons.append(f"first event was {events[0]!r}, expected 'start'")
    if result.token_count < 1:
        result.failure_reasons.append("expected at least one token event")
    if "done" not in events:
        result.failure_reasons.append("missing done event")
    if any(event == "error" for event in events):
        result.failure_reasons.append("received error event")

    start_index = _safe_index(events, "start")
    first_token_index = _safe_index(events, "token")
    done_index = _safe_index(events, "done")
    if first_token_index is not None and done_index is not None:
        if not (start_index is not None and start_index < first_token_index < done_index):
            result.failure_reasons.append("invalid event order; expected start → token(s) → done")

    if done_index is not None and any(event == "token" for event in events[done_index + 1 :]):
        result.failure_reasons.append("token event appeared after done")

    if result.first_token_latency_ms is None:
        result.failure_reasons.append("missing first token latency")
    if result.total_latency_ms is None:
        result.failure_reasons.append("missing total latency")

    if result.route is None:
        result.failure_reasons.append("missing answer_strategy in start event")
    elif result.route not in result.case.expected_routes:
        result.failure_reasons.append(
            f"unexpected route {result.route!r}; expected one of {sorted(result.case.expected_routes)}"
        )
    elif result.case.strict_route_match and len(result.case.expected_routes) == 1:
        expected = next(iter(result.case.expected_routes))
        if result.route != expected:
            result.failure_reasons.append(f"route {result.route!r} != expected {expected!r}")


def _safe_index(items: list[str], value: str) -> int | None:
    try:
        return items.index(value)
    except ValueError:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def format_event_chain(result: QueryResult) -> str:
    return f"start → {result.token_count} token(s) → done"


def print_query_result(result: QueryResult) -> None:
    print(SEPARATOR)
    print(f"Query: {result.case.question}")
    print(SUBSEPARATOR)
    route = result.route or "unknown"
    print(f"  Route: {route} ({result.case.category})")
    print(f"  Events: {format_event_chain(result)}")
    print(f"  First token latency: {format_ms(result.first_token_latency_ms)}")
    print(f"  Total latency: {format_ms(result.total_latency_ms)}")
    if result.cache_hit is not None:
        print(f"  Cache hit: {'yes' if result.cache_hit else 'no'}")
    if result.error_payloads:
        print(f"  Error payloads: {json.dumps(result.error_payloads, ensure_ascii=False)}")
    if result.failure_reasons:
        print(f"  Failure reasons: {'; '.join(result.failure_reasons)}")
    if result.exception_text:
        print(f"  Error: {result.exception_text}")
    print(f"  Status: {'✅ PASS' if result.passed else '❌ FAIL'}")


def average(values: Iterable[float | None]) -> float | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def run_cache_hit_check(api_url: str, timeout_seconds: float) -> tuple[bool, str]:
    question = "Kdo jste? "
    case = QueryCase(question, "cache-hit", frozenset({"identity_direct"}))
    first = run_stream_query(case, api_url, timeout_seconds)
    second = run_stream_query(case, api_url, timeout_seconds)

    reasons: list[str] = []
    if not first.passed:
        reasons.append("first run failed")
    if not second.passed:
        reasons.append("second run failed")
    if second.cache_hit is not True:
        reasons.append("second run did not report cache_hit=true")
    if second.total_latency_ms is None or second.total_latency_ms > 500.0:
        reasons.append("second run was not fast enough (>500 ms total)")
    return not reasons, "; ".join(reasons) if reasons else "ok"


def run_post_stream_cache_check(api_url: str, timeout_seconds: float) -> tuple[bool, str]:
    question = "Jak založím účet online? "
    case = QueryCase(question, "post-stream-cache", frozenset({"generic_llm"}), strict_route_match=True)
    first = run_stream_query(case, api_url, timeout_seconds)
    second = run_stream_query(case, api_url, timeout_seconds)

    reasons: list[str] = []
    if not first.passed:
        reasons.append("first run failed")
    if not second.passed:
        reasons.append("second run failed")
    if first.cache_hit is not False:
        reasons.append("first run should not be a cache hit")
    if first.token_count < 1:
        reasons.append("first run did not stream any token")
    if second.cache_hit is not True:
        reasons.append("second run did not use post-stream cache")
    return not reasons, "; ".join(reasons) if reasons else "ok"


def print_summary(results: list[QueryResult], cache_hit_ok: bool, cache_store_ok: bool) -> None:
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    errors = sum(1 for result in results if result.exception_text)
    print(SEPARATOR)
    print("SUMMARY")
    print(SUBSEPARATOR)
    print(f"Total queries:    {len(results)}")
    print(f"Passed:           {passed}")
    print(f"Failed:           {failed}")
    print(f"Errors:           {errors}")
    print(f"Avg first token:  {format_ms(average(result.first_token_latency_ms for result in results))}")
    print(f"Avg total:        {format_ms(average(result.total_latency_ms for result in results))}")
    print(f"Cache hit OK:     {'✅' if cache_hit_ok else '❌'}")
    print(f"Post-stream cache: {'✅' if cache_store_ok else '❌'}")
    print(SEPARATOR)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"Base backend URL (default: {DEFAULT_API_URL})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help=f"Per-query timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    configure_logging(args.verbose)

    results: list[QueryResult] = []
    for case in TEST_CASES:
        result = run_stream_query(case, api_url=args.api_url, timeout_seconds=args.timeout)
        results.append(result)
        print_query_result(result)

    cache_hit_ok, cache_hit_reason = run_cache_hit_check(args.api_url, args.timeout)
    if not cache_hit_ok:
        LOGGER.warning("Cache hit check failed: %s", cache_hit_reason)

    cache_store_ok, cache_store_reason = run_post_stream_cache_check(args.api_url, args.timeout)
    if not cache_store_ok:
        LOGGER.warning("Post-stream cache check failed: %s", cache_store_reason)

    print_summary(results, cache_hit_ok=cache_hit_ok, cache_store_ok=cache_store_ok)
    return 0 if all(result.passed for result in results) and cache_hit_ok and cache_store_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

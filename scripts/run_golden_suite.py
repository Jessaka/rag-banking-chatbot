#!/usr/bin/env python3
"""Golden query regression runner for the RB banking chatbot."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path("evals/datasets/golden_queries_v1.json")
DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = Path("evals/runs")
TIMEOUT_SECONDS = 60.0


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def normalize_api_url(api_url: str) -> str:
    parsed = urllib.parse.urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid API URL: {api_url}")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat"):
        final_path = path
    elif path == "":
        final_path = "/chat"
    else:
        final_path = f"{path}/chat"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, final_path, "", "", ""))


def load_dataset(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Dataset must be a JSON list: {path}")
    return data


def post_chat(question: str, api_url: str, *, timeout: float = TIMEOUT_SECONDS) -> tuple[dict[str, Any], float, int, str]:
    payload = json.dumps(
        {
            "question": question,
            "session_id": f"golden-{uuid.uuid4()}",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "golden-suite/1.0"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status_code = int(exc.code)
    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {"raw_response_body": body}
    return parsed, latency_ms, status_code, body


def contains_check(answer: str, expected_terms: list[str]) -> tuple[bool, list[str]]:
    answer_norm = normalize_text(answer)
    missing = [term for term in expected_terms if normalize_text(term) not in answer_norm]
    return not missing, missing


def not_contains_check(answer: str, forbidden_terms: list[str]) -> tuple[bool, list[str]]:
    answer_norm = normalize_text(answer)
    present = [term for term in forbidden_terms if normalize_text(term) in answer_norm]
    return not present, present


def strategy_check(actual: str | None, expected: str) -> bool:
    if not actual:
        return False
    return normalize_text(expected) in normalize_text(actual)


def confidence_check(actual: str | None, expected: str) -> bool:
    return normalize_text(actual or "") == normalize_text(expected)


def infer_behavior(result: dict[str, Any]) -> str:
    strategy = str(result.get("answer_strategy") or "")
    if strategy == "overview_fallback" or bool(result.get("degraded_answer")) and strategy == "overview_fallback":
        return "overview_fallback"
    if strategy in {"unsupported_direct", "fallback_no_answer"}:
        return "unsupported"
    if bool(result.get("clarification_required")) or strategy == "clarification_direct":
        return "clarification"
    return "direct_answer"


def stale_suppression_used(sources: list[Any]) -> bool:
    for source in sources or []:
        if isinstance(source, dict) and source.get("stale_source_suppressed") is True:
            return True
    return False


def evaluate_case(item: dict[str, Any], api_url: str) -> dict[str, Any]:
    result, latency_ms, status_code, raw_body = post_chat(item["question"], api_url)
    answer = str(result.get("answer") or "")
    route = result.get("answer_strategy")
    confidence = result.get("confidence_bucket") or result.get("answer_confidence")
    degradation_used = bool(result.get("degraded_answer"))
    stale_suppression = stale_suppression_used(result.get("sources") or [])
    behavior = infer_behavior(result)

    contains_ok, missing_terms = contains_check(answer, item.get("check_contains") or [])
    not_contains_ok, forbidden_terms = not_contains_check(answer, item.get("check_not_contains") or [])
    strategy_ok = strategy_check(route, item["expected_strategy"])
    confidence_ok = confidence_check(confidence, item["expected_confidence"])
    behavior_ok = behavior == item["expected_behavior"]
    http_ok = status_code == 200

    failures: list[str] = []
    if not http_ok:
        failures.append(f"http_status={status_code}")
    if not contains_ok:
        failures.append(f"missing_contains={missing_terms}")
    if not not_contains_ok:
        failures.append(f"forbidden_contains={forbidden_terms}")
    if not strategy_ok:
        failures.append(f"strategy_expected={item['expected_strategy']} actual={route}")
    if not confidence_ok:
        failures.append(f"confidence_expected={item['expected_confidence']} actual={confidence}")
    if not behavior_ok:
        failures.append(f"behavior_expected={item['expected_behavior']} actual={behavior}")

    return {
        "id": item["id"],
        "question": item["question"],
        "category": item["category"],
        "expected_strategy": item["expected_strategy"],
        "expected_confidence": item["expected_confidence"],
        "expected_behavior": item["expected_behavior"],
        "route": route,
        "confidence": confidence,
        "behavior": behavior,
        "degradation_used": degradation_used,
        "latency_ms": round(latency_ms, 1),
        "stale_suppression": stale_suppression,
        "status_code": status_code,
        "passed": not failures,
        "failures": failures,
        "answer_preview": answer[:500],
        "raw_body": raw_body if not http_ok else None,
    }


def print_result(row: dict[str, Any]) -> None:
    status = "PASS" if row["passed"] else "FAIL"
    print(
        f"[{status}] {row['id']} [{row['category']}] route={row['route']} "
        f"confidence={row['confidence']} degradation_used={row['degradation_used']} "
        f"latency={row['latency_ms']}ms stale_suppression={row['stale_suppression']}"
    )
    if row["failures"]:
        for failure in row["failures"]:
            print(f"  - {failure}")


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row["passed"])
    avg_latency = round(sum(row["latency_ms"] for row in results) / total, 1) if total else 0.0
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "passed": 0, "avg_latency_ms": 0.0})

    for row in results:
        bucket = by_category[row["category"]]
        bucket["total"] += 1
        bucket["passed"] += 1 if row["passed"] else 0
        bucket["avg_latency_ms"] += row["latency_ms"]

    for category, bucket in by_category.items():
        bucket["avg_latency_ms"] = round(bucket["avg_latency_ms"] / bucket["total"], 1) if bucket["total"] else 0.0
        bucket["pass_rate"] = round((bucket["passed"] / bucket["total"]) * 100.0, 1) if bucket["total"] else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total) * 100.0, 1) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "per_category": dict(sorted(by_category.items())),
    }


def save_report(output_dir: Path, dataset_path: Path, api_url: str, results: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"golden_suite_{timestamp}.json"
    payload = {
        "run_meta": {
            "dataset_path": str(dataset_path),
            "api_url": api_url,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "runner": "golden-suite-v1",
        },
        "summary": summary,
        "results": results,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run golden query regression suite against POST /chat.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Base API URL, e.g. http://localhost:8000")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to golden dataset JSON")
    parser.add_argument("--save-report", action="store_true", help="Save JSON report to output directory")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for saved reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    api_url = normalize_api_url(args.api_url)
    dataset = load_dataset(dataset_path)

    print(f"Loaded {len(dataset)} golden queries from {dataset_path}")
    print(f"Target endpoint: {api_url}")

    results: list[dict[str, Any]] = []
    for item in dataset:
        row = evaluate_case(item, api_url)
        results.append(row)
        print_result(row)

    summary = build_summary(results)
    print("\nSummary")
    print(f"- pass_rate: {summary['pass_rate']}% ({summary['passed']}/{summary['total']})")
    print(f"- avg_latency_ms: {summary['avg_latency_ms']}")
    print("- per_category:")
    for category, bucket in summary["per_category"].items():
        print(
            f"  - {category}: {bucket['passed']}/{bucket['total']} "
            f"({bucket['pass_rate']}%), avg_latency={bucket['avg_latency_ms']}ms"
        )

    if args.save_report:
        report_path = save_report(Path(args.output_dir), dataset_path, api_url, results, summary)
        print(f"Saved report: {report_path}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

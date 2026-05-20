#!/usr/bin/env python3
"""Local API eval runner for the RAG chatbot.

Evaluates retrieval + generation through the running FastAPI service. The runner
does not import or modify the retrieval/generation pipeline; it treats the API as
the contract under test.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path("evals/pricing_eval.json")
DEFAULT_API_URL = "http://localhost:8000/chat"
HALLUCINATION_MARKERS = (
    "nemohu najít",
    "nemohu najit",
    "kontaktujte podporu",
    "nemám informace",
    "nemam informace",
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def load_dataset(path: Path, only_category: str | None = None) -> list[dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError(f"Eval dataset must be a JSON list: {path}")
    if only_category:
        items = [item for item in items if item.get("category") == only_category]
    return items


def post_chat(question: str, api_url: str, timeout: float = 120.0) -> tuple[dict[str, Any], float, int, str]:
    payload = json.dumps({"question": question, "session_id": f"eval-{time.time_ns()}"}).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status_code = int(exc.code)
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw_response_body": body}
        parsed.setdefault("error", str(exc))
        parsed["response_body"] = body
        return parsed, time.perf_counter() - t0, status_code, body
    latency_s = time.perf_counter() - t0
    return json.loads(body), latency_s, status_code, body


def expected_contains_pass(answer: str, expected_contains: list[str]) -> tuple[bool, list[str]]:
    answer_norm = normalize_text(answer)
    missing = [term for term in expected_contains if normalize_text(term) not in answer_norm]
    return not missing, missing


def has_hallucination_failure(answer: str, category: str, sources: list[Any]) -> bool:
    if category != "pricing" or not sources:
        return False
    answer_norm = normalize_text(answer)
    return any(marker in answer_norm for marker in HALLUCINATION_MARKERS)


def evaluate_item(item: dict[str, Any], api_url: str, timeout: float = 120.0) -> dict[str, Any]:
    question = item["question"]
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        response, latency_s, status_code, response_body = post_chat(question, api_url, timeout=timeout)
        answer = response.get("answer", "")
        sources = response.get("sources", []) or []
        ok_contains, missing = expected_contains_pass(answer, item.get("expected_contains", []))
        hallucination_fail = has_hallucination_failure(answer, item.get("category", ""), sources)
        passed = status_code < 500 and ok_contains and not hallucination_fail
        error = response.get("error") if status_code >= 500 else None
    except Exception as exc:
        response = {}
        latency_s = 0.0
        status_code = None
        response_body = ""
        answer = ""
        sources = []
        missing = item.get("expected_contains", [])
        hallucination_fail = False
        passed = False
        error = str(exc)

    return {
        "question": question,
        "category": item.get("category"),
        "expected_contains": item.get("expected_contains", []),
        "missing_expected": missing,
        "pass": passed,
        "error": error,
        "status_code": status_code,
        "response_body": response_body,
        "error_payload": response if status_code and status_code >= 500 else None,
        "traceback": response.get("traceback"),
        "hallucination_fail": hallucination_fail,
        "answer": answer,
        "sources": sources,
        "processing_time_ms": response.get("processing_time_ms"),
        "latency_ms": round(latency_s * 1000, 1),
        "answer_strategy": response.get("answer_strategy", "unknown"),
        "request_id": response.get("request_id"),
        "retrieval_debug": response.get("retrieval_debug"),
        "pricing_retriever_result": response.get("pricing_retriever_result"),
        "hybrid_candidates": response.get("hybrid_candidates"),
        "min_confidence": item.get("min_confidence"),
        "started_at": started_at,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    avg_latency = sum(r.get("latency_ms") or 0 for r in results) / total if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "average_latency_ms": round(avg_latency, 1),
    }


def save_report(report: dict[str, Any], output_dir: Path = Path("evals/results")) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"eval_report_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_result(result: dict[str, Any]) -> None:
    status = "PASS" if result["pass"] else "FAIL"
    print(f"[{status}] {result['question']}")
    print(f"Latency: {(result.get('latency_ms') or 0) / 1000:.2f}s")
    print(f"Strategy: {result.get('answer_strategy', 'unknown')}")
    if not result["pass"]:
        if result.get("missing_expected"):
            print(f"Missing: {', '.join(result['missing_expected'])}")
        if result.get("hallucination_fail"):
            print("Hallucination heuristic: fallback/apology marker with non-empty pricing sources")
        if result.get("error"):
            print(f"Error: {result['error']}")
    print()


def run_eval(dataset_path: Path, api_url: str, only_category: str | None, timeout: float) -> dict[str, Any]:
    items = load_dataset(dataset_path, only_category=only_category)
    results = []
    for item in items:
        result = evaluate_item(item, api_url, timeout=timeout)
        print_result(result)
        results.append(result)
    summary = summarize(results)
    print("Summary")
    print(f"Accuracy: {summary['accuracy'] * 100:.1f}% ({summary['passed']}/{summary['total']})")
    print(f"Average latency: {summary['average_latency_ms'] / 1000:.2f}s")
    print(f"Fail count: {summary['failed']}")
    return {
        "dataset": str(dataset_path),
        "api_url": api_url,
        "only_category": only_category,
        "summary": summary,
        "results": results,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local API evals for the RAG chatbot.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--only-category", default=None)
    parser.add_argument("--save-report", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_eval(args.dataset, args.api_url, args.only_category, args.timeout)
    if args.save_report:
        path = save_report(report)
        print(f"Report saved: {path}")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

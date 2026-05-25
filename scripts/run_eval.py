#!/usr/bin/env python3
"""Banking RAG evaluation runner.

The runner evaluates the running FastAPI backend via ``POST /chat`` only. It
does not import retrieval/generation code, does not crawl, does not reindex and
does not touch Qdrant. Metrics are dataset-driven and work with normal API
responses; ``retrieval_debug`` is used only when the backend exposes it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path("evals/datasets/banking_eval_v1.json")
LEGACY_DATASET = Path("evals/pricing_eval.json")
DEFAULT_API_URL = "http://localhost:8000/chat"
RUNNER_VERSION = "banking-eval-v1"

HALLUCINATION_MARKERS = (
    "určitě", "zarucene", "garantuji", "bez zdroje", "vždy zdarma", "nikdy neplatíte",
)
FALLBACK_WITH_SOURCES_MARKERS = ("nemohu najít", "nemohu najit", "kontaktujte podporu", "nemám informace", "nemam informace")
UNSUPPORTED_CUES = (
    "nemám k dispozici", "nemam k dispozici", "nepodařilo se najít", "nepodarilo se najit",
    "nemohu ověřit", "nemohu overit", "obraťte se", "obratte se", "kontaktujte",
)
CLARIFICATION_CUES = ("upřesněte", "upresnete", "myslíte", "myslite", "zda jde", "který", "ktery")
PRICE_RE = re.compile(r"\b\d+[\s.]?\d*\s*(?:kč|kc|czk|eur|€)|\bzdarma\b|\bv ceně\b|\bv cene\b", re.I)


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
    req = urllib.request.Request(api_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
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
    return json.loads(body), time.perf_counter() - t0, status_code, body


def expected_contains_pass(answer: str, expected_contains: list[str]) -> tuple[bool, list[str]]:
    answer_norm = normalize_text(answer)
    missing = [term for term in expected_contains if normalize_text(term) not in answer_norm]
    return not missing, missing


def expected_not_contains_pass(answer: str, expected_not_contains: list[str]) -> tuple[bool, list[str]]:
    answer_norm = normalize_text(answer)
    present = [term for term in expected_not_contains if normalize_text(term) in answer_norm]
    return not present, present


def has_hallucination_failure(answer: str, category: str, sources: list[Any]) -> bool:
    answer_norm = normalize_text(answer)
    if any(marker in answer_norm for marker in HALLUCINATION_MARKERS):
        return True
    if category == "pricing" and sources and any(marker in answer_norm for marker in FALLBACK_WITH_SOURCES_MARKERS):
        return True
    return category == "pricing" and bool(PRICE_RE.search(answer_norm)) and not sources


def _source_text(sources: list[Any]) -> str:
    parts: list[str] = []
    for source in sources or []:
        if isinstance(source, dict):
            parts.extend(str(source.get(k) or "") for k in ("file_name", "title", "preview", "url"))
        else:
            parts.append(str(source))
    return " ".join(parts)


def source_grounding_score(answer: str, sources: list[Any], item: dict[str, Any]) -> float:
    requires_sources = bool(item.get("requires_sources", True))
    expected_sources = item.get("expected_sources", []) or []
    score = 0.0
    if sources or not requires_sources:
        score += 0.4
    src_norm = normalize_text(_source_text(sources))
    if expected_sources and any(normalize_text(src) in src_norm for src in expected_sources):
        score += 0.3
    elif not expected_sources and sources:
        score += 0.2
    answer_norm = normalize_text(answer)
    if "zdroj" in answer_norm or "source" in answer_norm or sources:
        score += 0.3
    return round(min(score, 1.0), 4)


def pricing_accuracy_pass(answer: str, item: dict[str, Any]) -> bool | None:
    expected_price = item.get("expected_price")
    if not expected_price:
        return None
    answer_norm = normalize_text(answer)
    allowed = [normalize_text(v) for v in expected_price.get("allow_text_values", [])]
    if allowed and any(v in answer_norm for v in allowed):
        return True
    amount = normalize_text(str(expected_price.get("amount") or ""))
    currency = normalize_text(str(expected_price.get("currency") or ""))
    period = normalize_text(str(expected_price.get("period") or ""))
    return bool(amount and amount in answer_norm and (not currency or currency in answer_norm) and (not period or period in answer_norm))


def ambiguity_correct(answer: str, item: dict[str, Any]) -> bool | None:
    answer_norm = normalize_text(answer)
    asks_clarification = any(cue in answer_norm for cue in CLARIFICATION_CUES)
    if item.get("should_clarify") is True:
        return asks_clarification and not bool(PRICE_RE.search(answer_norm))
    if item.get("should_clarify") is False:
        return not asks_clarification
    return None


def unsupported_correct(answer: str, item: dict[str, Any]) -> bool | None:
    if item.get("should_refuse_unsupported") is not True and item.get("unsupported_topic") is not True:
        return None
    answer_norm = normalize_text(answer)
    has_cue = any(cue in answer_norm for cue in UNSUPPORTED_CUES)
    gives_specific_price = bool(PRICE_RE.search(answer_norm))
    return has_cue and not gives_specific_price


def answer_formatting_pass(answer: str, item: dict[str, Any]) -> bool | None:
    expectations = item.get("format_expectations") or {}
    if not expectations:
        return None
    answer_norm = normalize_text(answer)
    if expectations.get("forbid_raw_json") and any(token in answer for token in ("```", "{", "}")):
        return False
    max_chars = expectations.get("max_answer_chars")
    if max_chars and len(answer) > int(max_chars):
        return False
    if expectations.get("requires_source_cue") and "zdroj" not in answer_norm and "source" not in answer_norm:
        return False
    if expectations.get("forbid_price_when_clarifying") and bool(PRICE_RE.search(answer_norm)):
        return False
    return True


def _debug_rows(retrieval_debug: Any) -> list[dict[str, Any]]:
    if isinstance(retrieval_debug, dict):
        rows = retrieval_debug.get("selected_pricing_rows") or retrieval_debug.get("sources") or []
        return rows if isinstance(rows, list) else []
    if isinstance(retrieval_debug, list):
        return [r for r in retrieval_debug if isinstance(r, dict)]
    return []


def retrieval_precision_at_k(result: dict[str, Any], item: dict[str, Any], k: int = 3) -> float | None:
    expected_products = [normalize_text(p) for p in item.get("expected_products", []) or []]
    expected_sources = [normalize_text(s) for s in item.get("expected_sources", []) or []]
    if not expected_products and not expected_sources:
        return None
    candidates: list[str] = []
    for row in _debug_rows(result.get("retrieval_debug")):
        candidates.append(normalize_text(" ".join(str(row.get(key) or "") for key in ("product_name", "source_file", "title", "file_name"))))
    if not candidates:
        for source in result.get("sources", []) or []:
            if isinstance(source, dict):
                candidates.append(normalize_text(" ".join(str(source.get(key) or "") for key in ("file_name", "title", "preview"))))
    if not candidates:
        return 0.0
    top = candidates[:k]
    relevant = 0
    for cand in top:
        if any(p and p in cand for p in expected_products) or any(s and s in cand for s in expected_sources):
            relevant += 1
    return round(relevant / max(1, min(k, len(top))), 4)


def confidence_bucket(result: dict[str, Any]) -> str:
    values: list[float] = []
    for row in _debug_rows(result.get("retrieval_debug")):
        for key in ("confidence", "rerank_score", "hybrid_score"):
            try:
                values.append(float(row.get(key)))
                break
            except Exception:
                continue
    if not values:
        try:
            values.append(float(result.get("processing_time_ms") or 0) / 10000.0)
        except Exception:
            return "unknown"
    avg = sum(values) / len(values)
    if avg >= 0.85:
        return "high"
    if avg >= 0.65:
        return "mid"
    return "low"


def classify_failure(item: dict[str, Any], result: dict[str, Any], metrics: dict[str, Any]) -> str | None:
    if result.get("status_code") and int(result["status_code"]) >= 500:
        return "api_error"
    if metrics.get("ambiguity_correct") is False:
        return "ambiguity_miss"
    if metrics.get("unsupported_correct") is False:
        return "unsupported_answer"
    if metrics.get("answer_formatting_pass") is False:
        return "format_mismatch"
    if item.get("requires_sources", True) and not result.get("sources") and item.get("expected_behavior") == "direct_answer":
        return "missing_retrieval"
    if item.get("expected_behavior") == "direct_answer" and metrics.get("retrieval_precision_at_3") == 0.0:
        return "missing_retrieval"
    not_present = result.get("unexpected_present") or []
    if not_present:
        if any("archiv" in normalize_text(v) or "2020" in v or "2018" in v for v in not_present):
            return "stale_pricing"
        return "wrong_product_routing"
    if metrics.get("pricing_accuracy_pass") is False:
        return "stale_pricing" if item.get("subcategory") == "pricing" else "format_mismatch"
    if metrics.get("hallucination_fail") is True:
        return "hallucination"
    if metrics.get("source_grounding_score", 1.0) < float(item.get("min_grounding_score", 0.0)):
        return "missing_source"
    if result.get("missing_expected"):
        return "format_mismatch"
    return None


def evaluate_item(item: dict[str, Any], api_url: str, timeout: float = 120.0) -> dict[str, Any]:
    question = item["question"]
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        response, latency_s, status_code, response_body = post_chat(question, api_url, timeout=timeout)
    except Exception as exc:
        response, latency_s, status_code, response_body = {"error": str(exc)}, 0.0, None, ""

    answer = response.get("answer", "") if isinstance(response, dict) else ""
    sources = response.get("sources", []) or [] if isinstance(response, dict) else []
    ok_contains, missing = expected_contains_pass(answer, item.get("expected_contains", []))
    ok_not_contains, unexpected_present = expected_not_contains_pass(answer, item.get("expected_not_contains", []))
    metrics = {
        "expected_contains_pass": ok_contains,
        "expected_not_contains_pass": ok_not_contains,
        "pricing_accuracy_pass": pricing_accuracy_pass(answer, item),
        "hallucination_fail": has_hallucination_failure(answer, item.get("category", ""), sources),
        "source_grounding_score": source_grounding_score(answer, sources, item),
        "ambiguity_correct": ambiguity_correct(answer, item),
        "unsupported_correct": unsupported_correct(answer, item),
        "answer_formatting_pass": answer_formatting_pass(answer, item),
        "retrieval_precision_at_3": None,
        "confidence_bucket": "unknown",
    }
    temp = {
        "status_code": status_code,
        "sources": sources,
        "retrieval_debug": response.get("retrieval_debug") if isinstance(response, dict) else None,
        "processing_time_ms": response.get("processing_time_ms") if isinstance(response, dict) else None,
        "missing_expected": missing,
        "unexpected_present": unexpected_present,
    }
    metrics["retrieval_precision_at_3"] = retrieval_precision_at_k({**temp, **response}, item, k=3) if isinstance(response, dict) else None
    metrics["confidence_bucket"] = confidence_bucket({**temp, **response}) if isinstance(response, dict) else "unknown"
    failure_type = classify_failure(item, temp, metrics)
    passed = status_code is not None and status_code < 500 and failure_type is None and ok_contains and ok_not_contains

    return {
        "id": item.get("id"),
        "question": question,
        "category": item.get("category"),
        "subcategory": item.get("subcategory"),
        "tags": item.get("tags", []),
        "expected_behavior": item.get("expected_behavior", "direct_answer"),
        "expected_contains": item.get("expected_contains", []),
        "expected_not_contains": item.get("expected_not_contains", []),
        "missing_expected": missing,
        "unexpected_present": unexpected_present,
        "passed": passed,
        "pass": passed,  # backwards-compatible tests/reports
        "failure_type": failure_type,
        "error": response.get("error") if isinstance(response, dict) else None,
        "status_code": status_code,
        "response_body": response_body,
        "answer": answer,
        "sources": sources,
        "processing_time_ms": response.get("processing_time_ms") if isinstance(response, dict) else None,
        "latency_ms": round(latency_s * 1000, 1),
        "answer_strategy": response.get("answer_strategy", "unknown") if isinstance(response, dict) else "unknown",
        "request_id": response.get("request_id") if isinstance(response, dict) else None,
        "retrieval_debug": response.get("retrieval_debug") if isinstance(response, dict) else None,
        "metrics": metrics,
        "started_at": started_at,
    }


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("pass") or r.get("passed"))
    pricing_cases = [r for r in results if r.get("metrics", {}).get("pricing_accuracy_pass") is not None]
    ambiguity_cases = [r for r in results if r.get("metrics", {}).get("ambiguity_correct") is not None]
    unsupported_cases = [r for r in results if r.get("metrics", {}).get("unsupported_correct") is not None]
    p3_values = [r["metrics"]["retrieval_precision_at_3"] for r in results if r.get("metrics", {}).get("retrieval_precision_at_3") is not None]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "average_latency_ms": round(sum(r.get("latency_ms") or 0 for r in results) / total, 1) if total else 0.0,
        "pricing_accuracy": round(sum(1 for r in pricing_cases if r["metrics"]["pricing_accuracy_pass"]) / len(pricing_cases), 4) if pricing_cases else None,
        "hallucination_rate": round(sum(1 for r in results if r.get("metrics", {}).get("hallucination_fail")) / total, 4) if total else 0.0,
        "unsupported_answer_rate": round(sum(1 for r in unsupported_cases if r["metrics"]["unsupported_correct"] is False) / len(unsupported_cases), 4) if unsupported_cases else None,
        "avg_source_grounding_score": _avg([r.get("metrics", {}).get("source_grounding_score", 0.0) for r in results]),
        "ambiguity_handling_correctness": round(sum(1 for r in ambiguity_cases if r["metrics"]["ambiguity_correct"]) / len(ambiguity_cases), 4) if ambiguity_cases else None,
        "retrieval_precision_at_3": _avg(p3_values),
    }


def _leaderboard(results: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        if field == "confidence_bucket":
            key = r.get("metrics", {}).get("confidence_bucket", "unknown")
        else:
            key = str(r.get(field) or "unknown")
        buckets[key].append(r)
    rows = []
    for key, items in sorted(buckets.items()):
        total = len(items)
        passed = sum(1 for i in items if i.get("passed"))
        rows.append({"name": key, "total": total, "passed": passed, "pass_rate": round(passed / total, 4) if total else 0.0})
    return rows


def build_leaderboards(results: list[dict[str, Any]]) -> dict[str, Any]:
    failures = Counter(r.get("failure_type") for r in results if r.get("failure_type"))
    return {
        "by_category": _leaderboard(results, "category"),
        "by_failure_type": [{"name": k, "count": v} for k, v in failures.most_common()],
        "by_confidence_bucket": _leaderboard(results, "confidence_bucket"),
    }


def failure_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    keys = ["missing_retrieval", "wrong_product_routing", "stale_pricing", "hallucination", "missing_source", "ambiguity_miss", "unsupported_answer", "api_error", "format_mismatch"]
    counts = Counter(r.get("failure_type") for r in results if r.get("failure_type"))
    return {key: counts.get(key, 0) for key in keys}


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


def markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Banking RAG Eval Report", "",
        "## Run metadata",
        f"- Dataset: `{report['run_meta']['dataset_path']}`",
        f"- API: `{report['run_meta']['api_url']}`",
        f"- Created: {report['run_meta']['created_at']}", "",
        "## KPI summary",
        f"- Pass rate: {s['pass_rate']:.1%} ({s['passed']}/{s['total']})",
        f"- Pricing accuracy: {s['pricing_accuracy'] if s['pricing_accuracy'] is not None else 'n/a'}",
        f"- Hallucination rate: {s['hallucination_rate']:.1%}",
        f"- Unsupported answer rate: {s['unsupported_answer_rate'] if s['unsupported_answer_rate'] is not None else 'n/a'}",
        f"- Avg source grounding score: {s['avg_source_grounding_score']}",
        f"- Ambiguity correctness: {s['ambiguity_handling_correctness'] if s['ambiguity_handling_correctness'] is not None else 'n/a'}",
        f"- Retrieval P@3: {s['retrieval_precision_at_3'] if s['retrieval_precision_at_3'] is not None else 'n/a'}", "",
        "## Category leaderboard", "| category | total | passed | pass_rate |", "|---|---:|---:|---:|",
    ]
    for row in report["leaderboards"]["by_category"]:
        lines.append(f"| {row['name']} | {row['total']} | {row['passed']} | {row['pass_rate']:.1%} |")
    lines.extend(["", "## Failure leaderboard", "| failure_type | count |", "|---|---:|"])
    for row in report["leaderboards"]["by_failure_type"]:
        lines.append(f"| {row['name']} | {row['count']} |")
    lines.extend(["", "## Failure samples"])
    for r in [r for r in report["results"] if r.get("failure_type")][:10]:
        lines.append(f"- `{r.get('failure_type')}` **{r.get('id')}**: {r.get('question')}")
    return "\n".join(lines) + "\n"


def save_report(report: dict[str, Any], output_dir: Path = Path("evals/runs"), markdown: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"banking_eval_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if markdown:
        path.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    return path


def update_leaderboard(report: dict[str, Any], path: Path = Path("evals/leaderboard.json")) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append({"run_meta": report["run_meta"], "summary": report["summary"], "leaderboards": report["leaderboards"]})
    path.write_text(json.dumps(history[-50:], ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Banking RAG Eval Leaderboard", "", "| created_at | dataset | total | pass_rate | hallucination_rate |", "|---|---|---:|---:|---:|"]
    for item in history[-20:]:
        sm = item["summary"]
        md.append(f"| {item['run_meta']['created_at']} | {Path(item['run_meta']['dataset_path']).name} | {sm['total']} | {sm['pass_rate']:.1%} | {sm['hallucination_rate']:.1%} |")
    path.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")


def print_result(result: dict[str, Any]) -> None:
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result.get('id') or ''} {result['question']}")
    print(f"Latency: {(result.get('latency_ms') or 0) / 1000:.2f}s | Strategy: {result.get('answer_strategy', 'unknown')}")
    if not result["passed"]:
        print(f"Failure: {result.get('failure_type')}")
        if result.get("missing_expected"):
            print(f"Missing: {', '.join(result['missing_expected'])}")
        if result.get("unexpected_present"):
            print(f"Unexpected: {', '.join(result['unexpected_present'])}")
    print()


def run_eval(dataset_path: Path, api_url: str, only_category: str | None, timeout: float, limit: int | None = None) -> dict[str, Any]:
    items = load_dataset(dataset_path, only_category=only_category)
    if limit:
        items = items[:limit]
    results = []
    for item in items:
        result = evaluate_item(item, api_url, timeout=timeout)
        print_result(result)
        results.append(result)
    summary = summarize(results)
    report = {
        "run_meta": {
            "dataset_path": str(dataset_path),
            "dataset_version": "banking_eval_v1",
            "api_url": api_url,
            "only_category": only_category,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "runner_version": RUNNER_VERSION,
            "git_sha": git_sha(),
        },
        "dataset": str(dataset_path),  # backwards compatibility
        "api_url": api_url,
        "only_category": only_category,
        "summary": summary,
        "leaderboards": build_leaderboards(results),
        "failures": failure_counts(results),
        "results": results,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    print("Summary")
    print(f"Pass rate: {summary['pass_rate'] * 100:.1f}% ({summary['passed']}/{summary['total']})")
    print(f"Average latency: {summary['average_latency_ms'] / 1000:.2f}s")
    print(f"Fail count: {summary['failed']}")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run API evals for the banking RAG chatbot.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET if DEFAULT_DATASET.exists() else LEGACY_DATASET)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--only-category", default=None)
    parser.add_argument("--save-report", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("evals/runs"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument("--update-leaderboard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_eval(args.dataset, args.api_url, args.only_category, args.timeout, limit=args.limit)
    if args.save_report:
        path = save_report(report, args.output_dir, markdown=not args.no_markdown)
        print(f"Report saved: {path}")
    if args.update_leaderboard:
        update_leaderboard(report)
        print("Leaderboard updated: evals/leaderboard.json")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

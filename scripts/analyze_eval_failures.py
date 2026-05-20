#!/usr/bin/env python3
"""Analyze latest eval report failures and suggest likely patches."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPORT_GLOB = "evals/results/eval_report_*.json"


def latest_report_path(root: Path = Path(".")) -> Path:
    reports = sorted(root.glob(REPORT_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        raise FileNotFoundError(f"No eval reports found: {REPORT_GLOB}")
    return reports[0]


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _status_code(item: dict[str, Any]) -> int | None:
    value = item.get("status_code") or item.get("http_status")
    if value is not None:
        try:
            return int(value)
        except Exception:
            pass
    text = " ".join(str(item.get(k) or "") for k in ("error", "traceback", "answer"))
    match = re.search(r"HTTP\s+Error\s+(\d+)|\bHTTP[:\s]+(\d{3})\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1) or match.group(2))
    return None


def _is_failure(item: dict[str, Any]) -> bool:
    status = _status_code(item)
    return (
        item.get("pass") is False
        or status == 500
        or item.get("answer_strategy") == "internal_error"
        or "internal server error" in str(item.get("error") or "").lower()
    )


def find_failures(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in report.get("results", []) if _is_failure(item)]


def infer_likely_cause(item: dict[str, Any]) -> tuple[str, str]:
    text = "\n".join(str(item.get(k) or "") for k in ("error", "traceback", "answer", "answer_strategy")).lower()
    sources = item.get("sources") or []
    question = str(item.get("question") or "").lower()

    if "attributeerror" in text and "metadata" in text:
        return (
            "dict/document mismatch",
            "Normalize source serialization so both LangChain Document and dict sources use a metadata/page_content adapter.",
        )
    if "nonetype" in text or "none has no attribute" in text or "'nonetype'" in text:
        return (
            "NoneType",
            "Guard optional fields before attribute access; add defaults for missing source/page/metadata fields.",
        )
    if "keyerror" in text or "missing" in text and "metadata" in text:
        return (
            "missing metadata",
            "Use metadata.get(...) with safe fallbacks in API/generation serializers.",
        )
    if "pricing" in str(item.get("category") or "").lower() and ("structured" in text or "pricing" in question) and _status_code(item) == 500:
        return (
            "malformed pricing row",
            "Validate structured pricing rows before formatting; require product_name, fee_type/fee_value and confidence >= 0.70.",
        )
    if "timeout" in text or "timed out" in text:
        return (
            "timeout",
            "Increase eval timeout or optimize the slow endpoint path; capture server-side timing for retrieval/LLM.",
        )
    if "gemini" in text or "anthropic" in text or "llm" in text or "model" in text:
        return (
            "LLM failure",
            "Add retry/fallback around LLM invocation and return a controlled error payload instead of HTTP 500.",
        )
    if not sources and _status_code(item) != 500:
        return (
            "empty sources",
            "Check retrieval thresholds/fallback hierarchy; for pricing queries ensure hybrid fallback runs when structured rows are empty.",
        )
    if _status_code(item) == 500:
        return (
            "internal server error; server traceback missing from eval report",
            "Enhance run_eval.py to store response body/traceback for HTTPError and inspect API logs for the exact stack trace.",
        )
    return (
        "expected_contains mismatch",
        "Review eval expected_contains or answer formatting; retrieval may be correct but wording differs.",
    )


def _format_sources(sources: list[Any], limit: int = 3) -> str:
    if not sources:
        return "-"
    lines = []
    for src in sources[:limit]:
        if isinstance(src, dict):
            meta = src.get("metadata", src)
            lines.append(
                f"- {meta.get('file_name') or meta.get('source_file') or meta.get('title') or 'neznámý'}"
                f" | page={meta.get('page')} | score={meta.get('rerank_score') or meta.get('pricing_retriever_score')}"
            )
        else:
            lines.append(f"- {src}")
    return "\n".join(lines)


def _format_retrieval_debug(item: dict[str, Any]) -> str:
    debug = item.get("retrieval_debug") or item.get("debug") or []
    if not debug:
        return "-"
    return json.dumps(debug[:3] if isinstance(debug, list) else debug, ensure_ascii=False, indent=2)


def print_failure(item: dict[str, Any]) -> None:
    status = _status_code(item)
    cause, patch = infer_likely_cause(item)
    error_payload = item.get("error_payload") or {}
    print("# FAIL QUERY")
    print()
    print(f"Question: {item.get('question', '-')}")
    print(f"HTTP: {status if status is not None else '-'}")
    print(f"Request ID: {item.get('request_id') or error_payload.get('request_id') or '-'}")
    print(f"Strategy: {item.get('answer_strategy') or error_payload.get('answer_strategy') or '-'}")
    print(f"Error: {item.get('error') or error_payload.get('error') or '-'}")
    print("Traceback:")
    print(item.get("traceback") or error_payload.get("traceback") or "-")
    print("Top sources:")
    print(_format_sources(item.get("sources") or error_payload.get("sources") or []))
    print("Retrieval debug:")
    print(_format_retrieval_debug(item) if item.get("retrieval_debug") else _format_retrieval_debug(error_payload))
    if item.get("response_body"):
        print("Response body:")
        print(str(item.get("response_body"))[:2000])
    print(f"Likely cause: {cause}")
    print(f"Suggested patch: {patch}")
    print()


def main() -> int:
    path = latest_report_path()
    report = load_report(path)
    failures = find_failures(report)
    print(f"Report: {path}")
    print(f"Failures found: {len(failures)}")
    print()
    for item in failures:
        print_failure(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

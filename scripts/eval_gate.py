#!/usr/bin/env python3
"""Automated regression gates for Banking RAG eval reports.

This script validates an existing eval JSON report against threshold config. It
does not call the backend, crawl, ingest, or touch Qdrant.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS = Path("evals/gates/regression_thresholds.json")


def _value(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if value is not None else None


def evaluate_gates(report: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    failures = report.get("failures", {}) or {}
    failed: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for metric, minimum in thresholds.get("minimums", {}).items():
        actual = _value(summary, metric)
        if actual is None:
            warnings.append({"type": "missing_metric", "metric": metric})
            continue
        if actual < float(minimum):
            failed.append({"type": "minimum", "metric": metric, "actual": actual, "expected": minimum})

    for metric, maximum in thresholds.get("maximums", {}).items():
        actual = _value(summary, metric)
        if actual is None:
            warnings.append({"type": "missing_metric", "metric": metric})
            continue
        if actual > float(maximum):
            failed.append({"type": "maximum", "metric": metric, "actual": actual, "expected": maximum})

    by_category = {row.get("name"): row for row in report.get("leaderboards", {}).get("by_category", [])}
    for category, minimum in thresholds.get("category_minimum_pass_rate", {}).items():
        row = by_category.get(category)
        if not row:
            warnings.append({"type": "missing_category", "category": category})
            continue
        actual = float(row.get("pass_rate", 0.0))
        if actual < float(minimum):
            failed.append({"type": "category_minimum", "category": category, "actual": actual, "expected": minimum})

    for failure_type, maximum in thresholds.get("failure_count_maximums", {}).items():
        actual = int(failures.get(failure_type, 0))
        if actual > int(maximum):
            failed.append({"type": "failure_count", "failure_type": failure_type, "actual": actual, "expected": maximum})

    return {
        "passed": not failed,
        "failed_gates": failed,
        "warnings": warnings,
        "priority_gates": thresholds.get("priority_gates", {}),
        "summary": summary,
    }


def markdown_gate_result(result: dict[str, Any]) -> str:
    lines = ["# Eval Regression Gate", "", f"Passed: **{result['passed']}**", ""]
    lines.append("## Failed gates")
    if not result["failed_gates"]:
        lines.append("- none")
    for gate in result["failed_gates"]:
        lines.append(f"- `{gate['type']}`: {gate}")
    lines.append("\n## Warnings")
    if not result["warnings"]:
        lines.append("- none")
    for warning in result["warnings"]:
        lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate eval report against regression gates.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    result = evaluate_gates(report, thresholds)
    print(markdown_gate_result(result))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        args.output.with_suffix(".md").write_text(markdown_gate_result(result), encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

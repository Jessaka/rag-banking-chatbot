#!/usr/bin/env python3
"""Compare two banking eval JSON reports for regression support."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


HARD_GATES = {
    "pass_rate": -0.03,
    "pricing_accuracy": -0.02,
    "hallucination_rate": 0.02,
    "unsupported_answer_rate": 0.02,
    "ambiguity_handling_correctness": -0.05,
}


def _metric(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if value is not None else None


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base_summary = baseline.get("summary", {})
    cand_summary = candidate.get("summary", {})
    deltas: dict[str, Any] = {}
    gates: list[dict[str, Any]] = []
    for key, threshold in HARD_GATES.items():
        base = _metric(base_summary, key)
        cand = _metric(cand_summary, key)
        if base is None or cand is None:
            deltas[key] = None
            continue
        delta = round(cand - base, 4)
        deltas[key] = delta
        failed = delta < threshold if threshold < 0 else delta > threshold
        if failed:
            gates.append({"metric": key, "baseline": base, "candidate": cand, "delta": delta, "threshold": threshold})

    base_results = {r.get("id") or r.get("question"): r for r in baseline.get("results", [])}
    cand_results = {r.get("id") or r.get("question"): r for r in candidate.get("results", [])}
    new_failures = []
    fixed_failures = []
    unchanged_failures = []
    for key, cand in cand_results.items():
        base = base_results.get(key)
        if not base:
            continue
        base_pass = bool(base.get("passed", base.get("pass")))
        cand_pass = bool(cand.get("passed", cand.get("pass")))
        if base_pass and not cand_pass:
            new_failures.append({"id": key, "failure_type": cand.get("failure_type"), "question": cand.get("question")})
        elif not base_pass and cand_pass:
            fixed_failures.append({"id": key, "question": cand.get("question")})
        elif not base_pass and not cand_pass:
            unchanged_failures.append({"id": key, "failure_type": cand.get("failure_type"), "question": cand.get("question")})

    return {
        "baseline_report_path": baseline.get("run_meta", {}).get("report_path"),
        "candidate_report_path": candidate.get("run_meta", {}).get("report_path"),
        "passed_regression_gates": not gates,
        "failed_gates": gates,
        "delta_summary": deltas,
        "new_failures": new_failures,
        "fixed_failures": fixed_failures,
        "unchanged_failures": unchanged_failures,
    }


def markdown_comparison(result: dict[str, Any]) -> str:
    lines = ["# Banking RAG Eval Comparison", "", f"Regression gates passed: **{result['passed_regression_gates']}**", "", "## Metric deltas"]
    for key, delta in result["delta_summary"].items():
        lines.append(f"- {key}: {delta}")
    lines.extend(["", "## Failed gates"])
    for gate in result["failed_gates"]:
        lines.append(f"- {gate['metric']}: {gate['baseline']} → {gate['candidate']} (Δ {gate['delta']})")
    lines.extend(["", "## New failures"])
    for item in result["new_failures"][:20]:
        lines.append(f"- `{item['failure_type']}` {item['id']}: {item['question']}")
    lines.extend(["", "## Fixed failures"])
    for item in result["fixed_failures"][:20]:
        lines.append(f"- {item['id']}: {item['question']}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two eval JSON reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    baseline.setdefault("run_meta", {})["report_path"] = str(args.baseline)
    candidate.setdefault("run_meta", {})["report_path"] = str(args.candidate)
    result = compare_reports(baseline, candidate)
    print(markdown_comparison(result))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        args.output.with_suffix(".md").write_text(markdown_comparison(result), encoding="utf-8")
    return 0 if result["passed_regression_gates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

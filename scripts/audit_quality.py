#!/usr/bin/env python3
"""Quality audit pro pricing rows a enterprise chunky.

Analyzes:
  - garbage ratio
  - duplicate ratio
  - OCR corruption ratio
  - pricing quality score
  - top noisy documents
  - top duplicate sources

Usage:
  python scripts/audit_quality.py
  python scripts/audit_quality.py --json-only
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.ingestion.quality_filters import (
    content_signature,
    filter_pricing_rows,
    is_garbage_chunk,
    is_garbage_text,
    is_low_information,
    score_chunk_quality,
    PricingQualityStats,
)
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)


def load_pricing_rows() -> list[dict[str, Any]]:
    path = config.PRICING_ROWS_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def audit_pricing_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit pricing rows for quality issues."""
    if not rows:
        return {"error": "Žádné pricing rows k auditu", "total": 0}

    # Run full quality filter
    valid, stats = filter_pricing_rows(rows)

    # Signature-based dedup detection
    sigs: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        sig = content_signature(f"{row.get('fee_type','')} {row.get('product_name','')} {row.get('fee_value','')}")
        sigs.setdefault(sig, []).append(i)
    # Count true duplicates (not first occurrence)
    true_dups = sum(max(0, len(v) - 1) for v in sigs.values())

    # Fee type distribution of garbage
    garbage_fee_types: Counter = Counter()
    for row in rows:
        fee = row.get("fee_type", "")
        if is_garbage_text(fee):
            garbage_fee_types[fee[:40]] += 1

    # Top sources of noisy data
    source_noise: Counter = Counter()
    for row in rows:
        src = row.get("source_file", row.get("source_url", "unknown"))
        combined = f"{row.get('fee_type','')} {row.get('product_name','')} {row.get('fee_value','')}"
        if is_garbage_text(combined):
            source_noise[src] += 1

    # Confidence distribution
    conf_hist: Counter = Counter()
    for row in rows:
        conf = int(float(row.get("confidence", 0)) * 10)
        conf_hist[f"{conf}/10"] += 1

    # Pricing value completeness
    no_value = sum(1 for r in rows if not r.get("fee_value"))
    no_product = sum(1 for r in rows if not r.get("product_name"))

    return {
        "total_rows": len(rows),
        "valid_after_filter": stats.valid_output,
        "filtered_total": stats.total_filtered,
        "filtered_header_artifacts": stats.filtered_header_artifact,
        "filtered_garbage_ocr": stats.filtered_garbage_ocr,
        "filtered_broken_unicode": stats.filtered_broken_unicode,
        "filtered_missing_fields": stats.filtered_missing_fields,
        "filtered_low_confidence": stats.filtered_low_confidence,
        "dedup_total_signatures": len(sigs),
        "dedup_duplicate_groups": sum(1 for v in sigs.values() if len(v) > 1),
        "dedup_true_duplicates": true_dups,
        "garbage_ratio": round(stats.total_filtered / max(len(rows), 1), 4),
        "duplicate_ratio": round(true_dups / max(len(rows), 1), 4),
        "ocr_corruption_pct": round(stats.filtered_garbage_ocr / max(len(rows), 1) * 100, 2),
        "rows_without_value": no_value,
        "rows_without_product": no_product,
        "confidence_distribution": dict(sorted(conf_hist.items())),
        "top_noisy_fee_types": garbage_fee_types.most_common(10),
        "top_noisy_sources": source_noise.most_common(10),
        "quality_score": round(stats.valid_output / max(len(rows), 1), 4) if rows else 0.0,
    }


def audit_enterprise_chunks(sample_size: int = 200, max_file_bytes: int = 200_000) -> dict[str, Any]:
    """Audit enterprise chunk quality from a sample of structured JSON files.

    Skips files larger than max_file_bytes to avoid PPTX/JSON monsters.
    """
    structured_dir = config.DATA_DIR / "crawl" / "structured"
    md_dir = config.DATA_DIR / "crawl" / "structured"

    chunks_found = 0
    garbage_chunks = 0
    nav_chunks = 0
    low_info_chunks = 0
    quality_scores: list[float] = []
    source_scores: dict[str, list[float]] = defaultdict(list)
    skipped_big = 0

    json_files = sorted(structured_dir.glob("*.json")) if structured_dir.exists() else []
    total_available = len(json_files)

    for json_path in json_files[:sample_size * 2]:  # scan more to get enough valid samples
        if len(quality_scores) >= sample_size:
            break
        # Skip big files (PPTX/JSON blobs)
        if json_path.stat().st_size > max_file_bytes:
            skipped_big += 1
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
            text = data.get("title", "") + " " + " ".join(
                s.get("content", "") for s in data.get("sections", [])
            )
            if len(text) > 50000:  # skip absurdly large texts
                skipped_big += 1
                continue
            score = score_chunk_quality(text)
            chunks_found += 1
            quality_scores.append(score["quality_score"])
            if score["is_garbage"]:
                garbage_chunks += 1
            if score["is_navigation"]:
                nav_chunks += 1
            if score["is_low_information"]:
                low_info_chunks += 1
            src = data.get("section", "unknown")
            source_scores[src].append(score["quality_score"])
        except Exception:
            continue

    return {
        "structured_chunks_found": total_available,
        "sampled": chunks_found,
        "skipped_big_files": skipped_big,
        "target_sample_size": sample_size,
        "garbage_chunks": garbage_chunks,
        "navigation_chunks": nav_chunks,
        "low_information_chunks": low_info_chunks,
        "avg_quality_score": round(
            sum(quality_scores) / max(len(quality_scores), 1), 3
        ),
        "worst_sections": sorted(
            [(src, round(sum(scores) / max(len(scores), 1), 3))
             for src, scores in source_scores.items()],
            key=lambda x: x[1],
        )[:10],
    }


def build_report() -> dict[str, Any]:
    pricing_rows = load_pricing_rows()
    pricing = audit_pricing_quality(pricing_rows)
    chunks = audit_enterprise_chunks()

    return {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "pricing_quality": pricing,
        "enterprise_chunk_quality": chunks,
        "summary_grade": _grade(pricing, chunks),
        "recommendations": _recommendations(pricing, chunks),
    }


def _grade(pricing: dict[str, Any], chunks: dict[str, Any]) -> str:
    if pricing.get("quality_score", 1) > 0.85 and chunks.get("avg_quality_score", 1) > 0.7:
        return "A"
    if pricing.get("quality_score", 1) > 0.70 and chunks.get("avg_quality_score", 1) > 0.5:
        return "B"
    if pricing.get("quality_score", 1) > 0.50:
        return "C"
    return "D"


def _recommendations(pricing: dict[str, Any], chunks: dict[str, Any]) -> list[str]:
    recs = []
    if pricing.get("garbage_ratio", 0) > 0.10:
        recs.append(
            f"Vysoký garbage ratio ({pricing['garbage_ratio']:.1%}). "
            f"Spusťte znovu pricing extraction s quality filteringem."
        )
    if pricing.get("duplicate_ratio", 0) > 0.05:
        recs.append(
            f"Duplicitní rows: {pricing['dedup_true_duplicates']} "
            f"({pricing['duplicate_ratio']:.1%}). Deduplikace doporučena."
        )
    if pricing.get("rows_without_value", 0) > 0:
        recs.append(f"Rows bez fee_value: {pricing['rows_without_value']}")
    if pricing.get("rows_without_product", 0) > 0:
        recs.append(f"Rows bez product_name: {pricing['rows_without_product']}")
    if chunks.get("garbage_chunks", 0) > 0:
        recs.append(f"Garbage chunků: {chunks['garbage_chunks']}")
    if chunks.get("navigation_chunks", 0) > 0:
        recs.append(f"Navigation chunků: {chunks['navigation_chunks']}")
    if not recs:
        recs.append("Kvalita dat je dobrá. Není potřeba akce.")
    return recs


@app.callback(invoke_without_command=True)
def main(json_only: bool = typer.Option(False, "--json-only", help="Jen JSON výstup.")) -> None:
    report = build_report()

    # Save report
    config.DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = config.DISCOVERY_DIR / "quality_audit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if json_only:
        console.print_json(json.dumps(report, ensure_ascii=False))
        return

    # ── Pricing quality table ───────────────────────────────────────────
    p = report["pricing_quality"]
    table = Table(title="Pricing rows quality audit")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k in ["total_rows", "valid_after_filter", "filtered_total",
              "garbage_ratio", "duplicate_ratio", "ocr_corruption_pct",
              "quality_score", "dedup_true_duplicates"]:
        v = p.get(k, "N/A")
        table.add_row(k.replace("_", " "), str(v))
    console.print(table)

    if p.get("top_noisy_sources"):
        src_table = Table(title="Top noisy sources")
        src_table.add_column("Source")
        src_table.add_column("Garbage rows", justify="right")
        for src, count in p["top_noisy_sources"][:8]:
            src_table.add_row(src[:60], str(count))
        console.print(src_table)

    # ── Chunk quality table ─────────────────────────────────────────────
    c = report["enterprise_chunk_quality"]
    ct = Table(title="Enterprise chunk quality")
    ct.add_column("Metric")
    ct.add_column("Value", justify="right")
    for k in ["structured_chunks_found", "garbage_chunks", "navigation_chunks",
              "low_information_chunks", "avg_quality_score"]:
        v = c.get(k, "N/A")
        ct.add_row(k.replace("_", " "), str(v))
    console.print(ct)

    console.print(f"\n[bold]Grade: {report['summary_grade']}[/bold]")
    for rec in report["recommendations"]:
        console.print(f"  • {rec}")


if __name__ == "__main__":
    app()

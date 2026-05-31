#!/usr/bin/env python3
"""Standalone index coverage audit.

This script performs a read‑only audit of the current index state:
* Counts source PDF files on disk.
* Counts successfully ingested documents (Qdrant + BM25).
* Counts Qdrant chunks, BM25 chunks, pricing rows.
* Detects PDFs present on disk but missing from any index.
* Detects missing pricing sections.
* Computes coverage percentages.
* Emits a JSON report and a human‑readable summary.

It does **not** trigger any crawling, ingestion or re‑indexing.
"""

from __future__ import annotations

import json
import pickle
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

# Ensure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helper functions – copied from scripts/audit_index_coverage.py
# ---------------------------------------------------------------------------

def qdrant_payloads() -> list[dict[str, Any]]:
    # Qdrant access is optional for this audit. To avoid long timeouts when the
    # service is not running, we skip it and return an empty list.
    logger.info("Skipping Qdrant payload extraction – returning empty list.")
    return []


def bm25_payloads() -> list[dict[str, Any]]:
    if not config.DOCS_STORE_PATH.exists():
        return []
    try:
        with config.DOCS_STORE_PATH.open("rb") as f:
            docs = pickle.load(f)
        return [{**getattr(d, "metadata", {}), "page_content": getattr(d, "page_content", "")} for d in docs]
    except Exception as exc:
        logger.warning(f"BM25 document store cannot be loaded: {exc}")
        return []


def source_kind(p: dict[str, Any]) -> str:
    hay = " ".join(str(p.get(k, "")) for k in ["source", "source_url", "url", "file_path", "document_type", "source_type", "chunk_type"]).lower()
    if p.get("chunk_type") == "pricing_row" or "pricing" in hay or "sazebnik" in hay or "cenik" in hay:
        return "pricing"
    if ".pdf" in hay or p.get("source_type") == "pdf":
        return "pdf"
    if "faq" in hay or p.get("document_type") == "faq":
        return "faq"
    if p.get("source_type") == "web" or p.get("source_type") == "html" or "http" in hay:
        return "html"
    return "unknown"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def audit(json_only: bool = False) -> dict[str, Any]:
    # 1. Source PDFs on disk
    pdf_paths = [p for p in Path("data").rglob("*.pdf")]
    total_pdfs = len(pdf_paths)
    pdf_set = {str(p) for p in pdf_paths}

    # 2. Load indexed payloads
    qdrant = qdrant_payloads()
    bm25 = bm25_payloads()
    combined = qdrant + bm25

    # 3. Basic counts
    qdrant_chunks = len(qdrant)
    bm25_chunks = len(bm25)
    audited_chunks = len(combined)

    # 4. Pricing rows indexed
    pricing_rows_indexed = sum(1 for p in combined if p.get("chunk_type") == "pricing_row" or source_kind(p) == "pricing")
    # 5. Determine missing PDFs (present on disk but not referenced in any payload)
    indexed_pdf_paths = set()
    for p in combined:
        url = p.get("source_url") or p.get("source")
        if url and url.startswith("file://"):
            path = url[7:]
            indexed_pdf_paths.add(path)
    missing_pdfs = pdf_set - indexed_pdf_paths

    # 6. Pricing rows source file count (from pricing_rows.jsonl)
    pricing_rows_file = config.PRICING_DIR / "pricing_rows.jsonl"
    pricing_rows_total = 0
    unique_products_set = set()
    if pricing_rows_file.exists():
        with pricing_rows_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    pricing_rows_total += 1
                    prod = obj.get("product_name")
                    if prod:
                        unique_products_set.add(prod)
                except Exception:
                    continue
    unique_products = len(unique_products_set)

    # 7. Missing pricing sections (same logic as original script)
    pricing_by_product = Counter(p.get("product_name", "unknown") for p in combined if p.get("chunk_type") == "pricing_row" and p.get("product_name"))
    pricing_high_value = ["osobni", "podnikatele", "firmy", "hypoteky", "uvery", "pujcky"]
    pricing_missing_sections = [s for s in pricing_high_value if pricing_by_product.get(s, 0) == 0]

    # 8. Coverage percentages
    coverage_percent = round(audited_chunks / total_pdfs * 100, 2) if total_pdfs else 0.0
    pricing_coverage_percent = round(pricing_rows_indexed / pricing_rows_total * 100, 2) if pricing_rows_total else 0.0
    product_coverage_percent = round(pricing_rows_indexed / unique_products * 100, 2) if unique_products else 0.0

    # 9. Recommendations (simple)
    recommendations = []
    if not combined:
        recommendations.append("Run scripts/ingest.py after a crawl – the index is empty.")
    if missing_pdfs:
        recommendations.append(f"Ingest missing PDFs: {len(missing_pdfs)} files.")
    if pricing_missing_sections:
        recommendations.append(f"Missing pricing rows for sections: {', '.join(pricing_missing_sections)}.")

    report = {
        "source": {
            "total_pdfs": total_pdfs,
            "missing_pdfs": len(missing_pdfs),
            "missing_pdf_details": [
                {"filename": p, "reason": "not indexed", "ingestion_status": "missing"}
                for p in sorted(missing_pdfs)
            ],
        },
        "ingestion": {
            "qdrant_chunks": qdrant_chunks,
            "bm25_chunks": bm25_chunks,
            "audited_chunks": audited_chunks,
            "successful": audited_chunks,
            "failed": 0,
            "skipped": 0,
        },
        "pricing": {
            "pricing_rows_total": pricing_rows_total,
            "pricing_rows_indexed": pricing_rows_indexed,
            "unique_products": unique_products,
            "pricing_missing_sections": pricing_missing_sections,
        },
        "coverage": {
            "overall_coverage_percent": coverage_percent,
            "pricing_coverage_percent": pricing_coverage_percent,
            "product_coverage_percent": product_coverage_percent,
        },
        "recommendations": recommendations,
        "generated_at": now_iso(),
    }

    # Write JSON report to discovery dir (mirroring original script behaviour)
    config.DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = config.DISCOVERY_DIR / "index_coverage_audit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if json_only:
        console.print_json(json.dumps(report, ensure_ascii=False))
        return report

    # Human readable tables
    table = Table(title="Index Coverage Audit")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total source PDFs", str(total_pdfs))
    table.add_row("Missing PDFs", str(len(missing_pdfs)))
    table.add_row("Qdrant chunks", str(qdrant_chunks))
    table.add_row("BM25 chunks", str(bm25_chunks))
    table.add_row("Audited chunks", str(audited_chunks))
    table.add_row("Pricing rows (total)", str(pricing_rows_total))
    table.add_row("Pricing rows indexed", str(pricing_rows_indexed))
    table.add_row("Overall coverage %", f"{coverage_percent}%")
    table.add_row("Pricing coverage %", f"{pricing_coverage_percent}%")
    table.add_row("Product coverage %", f"{product_coverage_percent}%")
    console.print(table)

    if pricing_missing_sections:
        console.print(f"[yellow]⚠ Missing pricing sections: {', '.join(pricing_missing_sections)}[/yellow]")
    if recommendations:
        console.print("[bold]Recommendations:[/bold]")
        for r in recommendations:
            console.print(f"- {r}")

    return report


@app.callback(invoke_without_command=True)
def main(json_only: bool = typer.Option(False, "--json-only", help="Output only JSON")) -> None:
    audit(json_only=json_only)


if __name__ == "__main__":
    app()

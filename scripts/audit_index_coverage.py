#!/usr/bin/env python3
"""Audit index coverage pro Qdrant + lokální BM25 document store."""

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

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)

HIGH_VALUE = ["html", "pdf", "pricing", "kreditni-karty", "debetni-karty", "faq", "bezpecnost"]
CREDIT_TERMS = {"kreditni_karta": ["kreditni", "kreditní", "kreditka"], "debetni_karta": ["debetni", "debetní"], "mastercard": ["mastercard"], "visa": ["visa"], "easy_karta": ["easy"], "style_karta": ["style"]}
TREND_HISTORY_PATH = config.DISCOVERY_DIR / "index_trend.jsonl"


def qdrant_payloads() -> list[dict[str, Any]]:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
        payloads, offset = [], None
        while True:
            points, offset = client.scroll(collection_name=config.QDRANT_COLLECTION, limit=1000, offset=offset, with_payload=True, with_vectors=False)
            payloads.extend([dict(p.payload or {}) for p in points])
            if offset is None:
                break
        return payloads
    except Exception as exc:
        logger.warning(f"Qdrant není dostupný nebo kolekce neexistuje: {exc}")
        return []


def bm25_payloads() -> list[dict[str, Any]]:
    if not config.DOCS_STORE_PATH.exists():
        return []
    try:
        with config.DOCS_STORE_PATH.open("rb") as f:
            docs = pickle.load(f)
        return [{**getattr(d, "metadata", {}), "page_content": getattr(d, "page_content", "")} for d in docs]
    except Exception as exc:
        logger.warning(f"BM25 document store nelze načíst: {exc}")
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


def section_kind(p: dict[str, Any]) -> str:
    explicit = p.get("section") or p.get("category")
    if explicit:
        return str(explicit)
    hay = " ".join(str(v) for v in p.values()).lower()
    rules = [("kreditni-karty", ["kredit", "mastercard", "visa", "easy", "style"]), ("debetni-karty", ["debet"]), ("bezpecnost", ["bezpec", "bezpeč", "phishing"]), ("faq", ["faq", "časté dotazy"]), ("hypoteky", ["hypotek"]), ("pricing", ["sazebnik", "sazebník", "cenik", "ceník"])]
    for sec, needles in rules:
        if any(n in hay for n in needles):
            return sec
    return "general"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit(json_only: bool = False) -> dict[str, Any]:
    q = qdrant_payloads()
    b = bm25_payloads()
    combined = q or b
    by_source = Counter(source_kind(p) for p in combined)
    by_section = Counter(section_kind(p) for p in combined)
    pricing_rows = sum(1 for p in combined if p.get("chunk_type") == "pricing_row" or source_kind(p) == "pricing")
    # Pricing metadata depth
    pricing_chunks = [p for p in combined if p.get("chunk_type") == "pricing_row"]
    pricing_confidence_scores = [float(p.get("confidence", 0)) for p in pricing_chunks if p.get("confidence")]
    avg_pricing_confidence = round(sum(pricing_confidence_scores) / len(pricing_confidence_scores), 3) if pricing_confidence_scores else None
    pricing_by_product = Counter(p.get("product_name", "unknown") for p in pricing_chunks if p.get("product_name"))
    hay = " ".join(" ".join(str(p.get(k, "")) for k in ["source_url", "url", "title", "page_content", "product_name"]) for p in combined).lower()
    credit = {key: {"covered": any(term in hay for term in terms), "chunks": sum(1 for p in combined if any(term in " ".join(str(v).lower() for v in p.values()) for term in terms))} for key, terms in CREDIT_TERMS.items()}
    missing = [item for item in HIGH_VALUE if by_source.get(item, 0) == 0 and by_section.get(item, 0) == 0]
    # Pricing specific missing detection
    pricing_high_value = ["osobni", "podnikatele", "firmy", "hypoteky", "uvery", "pujcky"]
    pricing_missing = [s for s in pricing_high_value if pricing_by_product.get(s, 0) == 0]
    recommendations = (["Spusťte scripts/ingest.py po enterprise crawlu, protože index je prázdný."] if not combined else []) + (["Doplnit crawl/ingest pro: " + ", ".join(missing)] if missing else []) + (["Chybí pricing rows pro sekce: " + ", ".join(pricing_missing)] if pricing_missing else [])
    return {
        "qdrant_chunks": len(q), "bm25_chunks": len(b), "audited_chunks": len(combined),
        "by_source_type": dict(by_source), "by_section": dict(by_section),
        "pricing_rows_indexed": pricing_rows,
        "avg_pricing_confidence": avg_pricing_confidence,
        "pricing_by_product": dict(pricing_by_product),
        "pricing_missing_sections": pricing_missing,
        "missing_sections_or_types": missing,
        "credit_card_chunk_coverage": credit,
        "recommendations": recommendations,
    }


@app.callback(invoke_without_command=True)
def main(json_only: bool = typer.Option(False, "--json-only", help="Jen JSON výstup, bez tabulek.")) -> None:
    report = audit(json_only=json_only)
    config.DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = config.DISCOVERY_DIR / "index_audit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Append trend snapshot
    try:
        TREND_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        trend = {k: report.get(k) for k in ["qdrant_chunks", "bm25_chunks", "audited_chunks", "pricing_rows_indexed", "avg_pricing_confidence", "missing_sections_or_types"]}
        trend["generated_at"] = now_iso()
        with TREND_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trend, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning(f"Nepodařilo se zapsat trend: {exc}")
    if json_only:
        console.print_json(json.dumps(report, ensure_ascii=False))
        return
    table = Table(title="Index coverage audit")
    table.add_column("Metric"); table.add_column("Value", justify="right")
    for k in ["qdrant_chunks", "bm25_chunks", "audited_chunks", "pricing_rows_indexed"]:
        table.add_row(k, str(report[k]))
    if report.get("avg_pricing_confidence") is not None:
        table.add_row("avg_pricing_confidence", str(report["avg_pricing_confidence"]))
    console.print(table)
    sec = Table(title="Chunks by source/type")
    sec.add_column("Type"); sec.add_column("Chunks", justify="right")
    for k, v in sorted(report["by_source_type"].items()):
        sec.add_row(k, str(v))
    console.print(sec)
    if report.get("pricing_missing_sections"):
        console.print(f"[yellow]⚠ Chybí pricing rows pro sekce: {', '.join(report['pricing_missing_sections'])}[/yellow]")
    console.print_json(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    app()

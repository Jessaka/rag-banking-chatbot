#!/usr/bin/env python3
"""Coverage audit pro rb.cz crawl + dokumenty + Qdrant + BM25."""

from __future__ import annotations

import json
import pickle
import sys
from collections import Counter, defaultdict
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

SECTIONS = ["osobni", "podnikatele", "firmy", "hypoteky", "pujcky", "uvery", "kreditni-karty", "debetni-karty", "investice", "sporeni", "pojisteni", "bezpecnost", "premium", "ceniky", "sazebniky", "dokumenty", "podminky", "faq", "api", "kurzy", "bankovnictvi", "mobilni-aplikace", "general"]
CREDIT_KEYS = {"kreditni_karta": ["kreditni", "kreditní", "kreditka"], "debetni_karta": ["debetni", "debetní"], "mastercard": ["mastercard"], "visa": ["visa"], "easy_karta": ["easy"], "style_karta": ["style"]}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Nelze načíst JSON {path}: {exc}")
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def classify(text: str) -> str:
    h = text.lower()
    rules = [("kreditni-karty", ["kredit", "mastercard", "visa", "easy", "style"]), ("debetni-karty", ["debet"]), ("hypoteky", ["hypotek"]), ("pujcky", ["pujck", "půjčk"]), ("uvery", ["uver", "úvěr"]), ("ceniky", ["cenik", "ceník"]), ("sazebniky", ["sazebnik", "sazebník"]), ("podminky", ["podmink", "podmínk", "vop"]), ("dokumenty", ["dokument"]), ("faq", ["faq", "caste-dotazy", "časté dotazy"]), ("bezpecnost", ["bezpec", "bezpeč"]), ("investice", ["invest", "fond"]), ("sporeni", ["sporen", "spořen"]), ("pojisteni", ["pojist"]), ("bankovnictvi", ["bankovnictv"]), ("mobilni-aplikace", ["mobilni", "mobilní", "aplikace"]), ("podnikatele", ["podnikatel"]), ("firmy", ["firmy"]), ("osobni", ["osobni", "osobní"])]
    for sec, needles in rules:
        if any(n in h for n in needles):
            return sec
    return "general"


def qdrant_payloads() -> list[dict[str, Any]]:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
        payloads, offset = [], None
        while True:
            points, offset = client.scroll(config.QDRANT_COLLECTION, limit=1000, offset=offset, with_payload=True, with_vectors=False)
            payloads.extend([dict(p.payload or {}) for p in points])
            if offset is None:
                break
        return payloads
    except Exception as exc:
        logger.warning(f"Qdrant audit přeskočen: {exc}")
        return []


def bm25_documents() -> list[Any]:
    if not config.DOCS_STORE_PATH.exists():
        return []
    try:
        with config.DOCS_STORE_PATH.open("rb") as f:
            return pickle.load(f)
    except Exception as exc:
        logger.warning(f"BM25 audit přeskočen: {exc}")
        return []


def find_duplicate_and_empty_files() -> tuple[list[dict[str, Any]], list[str]]:
    hashes: dict[str, list[str]] = defaultdict(list)
    empty = []
    for path in config.DOCUMENTS_DIR.rglob("*") if config.DOCUMENTS_DIR.exists() else []:
        if not path.is_file() or path.name == "metadata.jsonl":
            continue
        if path.stat().st_size == 0:
            empty.append(str(path))
            continue
        import hashlib
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[h].append(str(path))
    dups = [{"sha256": h, "files": files} for h, files in hashes.items() if len(files) > 1]
    return dups, empty


def build_report() -> dict[str, Any]:
    crawl_log = read_jsonl(config.CRAWL_DIR / "crawl_log.jsonl")
    doc_meta = read_jsonl(config.DOCUMENTS_DIR / "metadata.jsonl")
    sitemap_data = read_json(config.DISCOVERY_DIR / "sitemaps.json", {"urls": []})
    sitemap_urls = sitemap_data.get("urls", []) if isinstance(sitemap_data, dict) else []
    crawled_ok = [r for r in crawl_log if r.get("status") == "ok"]
    crawled_urls = {r.get("url") for r in crawled_ok if r.get("url")}
    sitemap_url_set = {r.get("url") for r in sitemap_urls if r.get("url")}
    by_section: dict[str, dict[str, Any]] = {}
    for sec in SECTIONS:
        crawled = sum(1 for r in crawled_ok if (r.get("section") or classify(r.get("url", ""))) == sec)
        sitemap = sum(1 for r in sitemap_urls if (r.get("section") or classify(r.get("url", ""))) == sec)
        by_section[sec] = {"crawled": crawled, "sitemap": sitemap, "coverage_pct": round((crawled / sitemap * 100) if sitemap else 0.0, 2)}
    qpayloads = qdrant_payloads()
    bdocs = bm25_documents()
    total_indexed = max(len(qpayloads), len(bdocs))
    ext_counts = Counter((m.get("extension") or Path(m.get("path", "")).suffix.lstrip(".") or "unknown").lower() for m in doc_meta)
    ext_counts["html"] = len(crawled_ok)
    ext_counts["faq"] = sum(1 for r in crawled_ok if r.get("section") == "faq" or "faq" in str(r).lower())
    pricing_rows = sum(1 for p in qpayloads if p.get("chunk_type") == "pricing_row")
    if not pricing_rows:
        pricing_rows = sum(1 for d in bdocs if getattr(d, "metadata", {}).get("chunk_type") == "pricing_row")
    duplicate_files, empty_files = find_duplicate_and_empty_files()
    broken = [m for m in doc_meta if m.get("status") not in {"ok", None} or (m.get("path") and not Path(m["path"]).exists())]
    failures = [r for r in crawl_log if str(r.get("status", "")).endswith("failed") or r.get("status") == "failed"]
    depth_dist = Counter(str(r.get("depth", 0)) for r in crawled_ok)
    haystack = " ".join([str(r.get("url", "")) + " " + str(r.get("title", "")) for r in crawled_ok] + [str(m.get("url", "")) for m in doc_meta]).lower()
    credit = {key: any(n in haystack for n in needles) for key, needles in CREDIT_KEYS.items()}
    missing_high = [s for s in ["hypoteky", "kreditni-karty", "debetni-karty", "ceniky", "sazebniky", "podminky", "bezpecnost", "faq"] if by_section[s]["coverage_pct"] < 50]
    top_uncovered = sorted(list(sitemap_url_set - crawled_urls))[:100]
    recommendations = []
    if missing_high:
        recommendations.append("Navýšit explicitní seed URL / max-pages pro high-value sekce: " + ", ".join(missing_high))
    if failures:
        recommendations.append("Spustit enterprise_crawl.py --resume pro retry failed URL.")
    if any(not v for v in credit.values()):
        recommendations.append("Doplnit explicitní crawl kreditních/debetních karet a dokumentů Mastercard/Visa/EASY/STYLE.")
    return {"total_crawled_urls": len(crawled_urls), "total_indexed_docs": total_indexed, "total_pdfs": ext_counts.get("pdf", 0), "total_pricing_rows": pricing_rows, "sitemap_coverage_percent": round((len(crawled_urls & sitemap_url_set) / len(sitemap_url_set) * 100) if sitemap_url_set else 0.0, 2), "by_section": by_section, "by_document_type": dict(ext_counts), "missing_high_value_sections": missing_high, "top_uncovered_urls": top_uncovered, "duplicate_files": duplicate_files, "empty_files": empty_files, "broken_downloads": broken, "http_failures": failures, "crawl_depth_distribution": dict(depth_dist), "credit_card_coverage": credit, "recommendations": recommendations}


@app.callback(invoke_without_command=True)
def main() -> None:
    report = build_report()
    config.DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    (config.DISCOVERY_DIR / "coverage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    table = Table(title="rb.cz coverage audit")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k in ["total_crawled_urls", "total_indexed_docs", "total_pdfs", "total_pricing_rows", "sitemap_coverage_percent"]:
        table.add_row(k, str(report[k]))
    console.print(table)
    sec = Table(title="Coverage by section")
    sec.add_column("Section"); sec.add_column("Crawled", justify="right"); sec.add_column("Sitemap", justify="right"); sec.add_column("%", justify="right")
    for name, row in report["by_section"].items():
        sec.add_row(name, str(row["crawled"]), str(row["sitemap"]), str(row["coverage_pct"]))
    console.print(sec)
    console.print_json(json.dumps({"missing_high_value_sections": report["missing_high_value_sections"], "credit_card_coverage": report["credit_card_coverage"], "recommendations": report["recommendations"]}, ensure_ascii=False))


if __name__ == "__main__":
    app()

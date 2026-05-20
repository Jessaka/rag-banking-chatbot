#!/usr/bin/env python3
"""Dataset diagnostics for enterprise rb.cz RAG corpus."""

from __future__ import annotations

import hashlib
import json
import pickle
import statistics
import sys
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

import config

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()


def _load_chunks(docs_store: Path) -> list:
    if not docs_store.exists():
        return []
    with docs_store.open("rb") as f:
        return pickle.load(f)


def _top(counter: Counter, n: int = 12) -> str:
    return "\n".join(f"{k}: {v}" for k, v in counter.most_common(n)) or "-"


@app.command()
def main(
    structured_dir: Path = typer.Option(config.DATA_DIR / "crawl" / "structured", "--structured-dir"),
    documents_dir: Path = typer.Option(config.DATA_DIR / "documents", "--documents-dir"),
    docs_store: Path = typer.Option(config.DOCS_STORE_PATH, "--docs-store"),
) -> None:
    structured_json = list(structured_dir.glob("*.json")) if structured_dir.exists() else []
    pdfs = list(documents_dir.glob("*.pdf")) if documents_dir.exists() else []
    chunks = _load_chunks(docs_store)

    lengths = [len(c.page_content) for c in chunks]
    chunk_types = Counter(c.metadata.get("chunk_type", "unknown") for c in chunks)
    source_types = Counter(c.metadata.get("source_type", "unknown") for c in chunks)
    categories = Counter(c.metadata.get("category", "unknown") for c in chunks)
    pricing_types = Counter(c.metadata.get("pricing_type", "unknown") or "none" for c in chunks)
    pricing_rows = [c for c in chunks if c.metadata.get("chunk_type") == "pricing_row"]
    pricing_row_products = Counter(str(c.metadata.get("product_name") or "").strip() or "<empty>" for c in pricing_rows)
    pricing_row_fee_types = Counter(str(c.metadata.get("fee_type") or "").strip() or "<empty>" for c in pricing_rows)
    doc_types = Counter(c.metadata.get("document_type", "unknown") for c in chunks)
    titles = Counter(c.metadata.get("title", "unknown") for c in chunks)
    filenames_by_category: dict[str, Counter] = {}
    for chunk in chunks:
        category = chunk.metadata.get("category", "unknown")
        filename = chunk.metadata.get("file_name") or Path(str(chunk.metadata.get("source", "unknown"))).name
        filenames_by_category.setdefault(category, Counter())[filename] += 1

    pdf_rows = []
    metadata_path = documents_dir / "metadata.jsonl"
    if metadata_path.exists():
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            try:
                pdf_rows.append(json.loads(line))
            except Exception:
                pass
    retail_pdfs = [r for r in pdf_rows if "osob" in " ".join(str(r.get(k, "")) for k in ("url", "filename", "title")).lower() or "ekonto" in str(r).lower()]
    corporate_pdfs = [r for r in pdf_rows if any(k in " ".join(str(r.get(x, "")) for x in ("url", "filename", "title")).lower() for k in ("firmy", "podnikatel", "corporate", "corp", "firem"))]

    content_hashes = Counter(hashlib.sha256(c.page_content.strip().lower().encode()).hexdigest() for c in chunks)
    duplicate_chunks = sum(count - 1 for count in content_hashes.values() if count > 1)

    table = Table(title="RAG dataset statistics", border_style="cyan", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Structured URLs", str(len(structured_json)))
    table.add_row("PDF files", str(len(pdfs)))
    table.add_row("Chunks", str(len(chunks)))
    table.add_row("Avg chunk length", f"{statistics.mean(lengths):.0f}" if lengths else "0")
    table.add_row("Median chunk length", f"{statistics.median(lengths):.0f}" if lengths else "0")
    table.add_row("Min / Max chunk length", f"{min(lengths)} / {max(lengths)}" if lengths else "0 / 0")
    table.add_row("Duplicate chunks", str(duplicate_chunks))
    table.add_row("Chunk types", _top(chunk_types))
    table.add_row("Source types", _top(source_types))
    table.add_row("Document types", _top(doc_types))
    table.add_row("Categories", _top(categories))
    table.add_row("Pricing types", _top(pricing_types))
    table.add_row("BM25 pricing_row chunks", f"{len(pricing_rows)} ({sum(1 for c in pricing_rows if c.page_content.strip())} non-empty)")
    table.add_row("Top pricing_row product_name", _top(pricing_row_products))
    table.add_row("Top pricing_row fee_type", _top(pricing_row_fee_types))
    table.add_row("Retail PDFs (heuristic)", str(len(retail_pdfs)))
    table.add_row("Corporate PDFs (heuristic)", str(len(corporate_pdfs)))
    table.add_row(
        "Top filenames by category",
        "\n\n".join(
            f"{cat}:\n{_top(counter, 5)}"
            for cat, counter in sorted(filenames_by_category.items())
            if cat in {"retail", "corporate", "cards", "mortgages", "investing", "insurance"}
        ) or "-",
    )
    table.add_row("Top titles", _top(titles, 8))

    console.print(Panel.fit("[bold cyan]RB RAG Dataset Debug[/bold cyan]", border_style="cyan"))
    console.print(table)

    try:
        from src.retrieval.vector_retriever import qdrant_pricing_row_debug
        qdebug = qdrant_pricing_row_debug()
        console.print("\n[bold]Qdrant pricing_row coverage[/bold]")
        console.print_json(json.dumps(qdebug, ensure_ascii=False))
    except Exception as exc:
        console.print(f"\n[yellow]Qdrant pricing_row coverage nelze načíst: {exc}[/yellow]")

    manifest = config.DATA_DIR / "ingestion_manifest.json"
    if manifest.exists():
        console.print("\n[bold]Ingestion manifest[/bold]")
        console.print_json(manifest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    app()

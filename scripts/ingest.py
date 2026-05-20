#!/usr/bin/env python3
"""
CLI skript pro spuštění ingestion pipeline.

Workflow:
  1. Stažení PDF dokumentů (z URL nebo lokálního adresáře)
  2. Parsování a čistění textu
  3. Rozdělení na chunky
  4. Indexace do Qdrant + BM25

Použití:
  # Stažení z URL definovaných v config.py
  python scripts/ingest.py

  # Stažení z vlastního souboru s URL (jeden URL na řádek)
  python scripts/ingest.py --urls-file data/sources.txt

  # Zpracování lokálních PDF bez stahování
  python scripts/ingest.py --skip-download

  # Přidání nových dokumentů bez smazání existující kolekce (výchozí)
  python scripts/ingest.py --incremental

  # Kompletní reindexace od nuly (maže existující kolekci)
  python scripts/ingest.py --full
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Přidáme projekt do Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.ingestion.chunker import chunk_documents
from src.ingestion.downloader import download_all, load_urls_from_file
from src.ingestion.enterprise import build_enterprise_chunks, reclassify_metadata
from src.ingestion.indexer import run_full_indexing, run_incremental_indexing
from src.ingestion.parser import parse_all_pdfs
from src.ingestion.pricing_extractor import extract_pricing_rows_from_dir
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)


@app.command()
def main(
    urls_file: Path = typer.Option(
        None,
        "--urls-file",
        "-u",
        help="Soubor s URL (jeden na řádek). Přepíše URL z config.py.",
        exists=False,
    ),
    pdf_dir: Path = typer.Option(
        config.RAW_DIR,
        "--pdf-dir",
        "-d",
        help="Adresář s PDF soubory ke zpracování.",
    ),
    skip_download: bool = typer.Option(
        False,
        "--skip-download",
        "-s",
        help="Přeskočí stahování, zpracuje existující PDF v pdf_dir.",
    ),
    chunk_size: int = typer.Option(
        config.CHUNK_SIZE,
        "--chunk-size",
        help="Maximální délka chunku ve znacích.",
    ),
    chunk_overlap: int = typer.Option(
        config.CHUNK_OVERLAP,
        "--chunk-overlap",
        help="Překryv sousedních chunků.",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Kompletní reindexace: smaže existující kolekci a indexuje vše znovu. "
            "Použijte při změně embed modelu nebo chunking parametrů."
        ),
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Pokračuje v rozpracované full indexaci bez přepsání existující Qdrant kolekce.",
    ),
    enterprise: bool = typer.Option(
        False,
        "--enterprise",
        help="Ingestuje structured crawl JSON/Markdown a data/documents PDF enterprise chunkingem.",
    ),
    structured_dir: Path = typer.Option(
        config.DATA_DIR / "crawl" / "structured",
        "--structured-dir",
        help="Adresář se structured JSON/Markdown z scripts/crawl_rb.py.",
    ),
    documents_dir: Path = typer.Option(
        config.DATA_DIR / "documents",
        "--documents-dir",
        help="Adresář s PDF dokumenty ze scripts/download_documents.py.",
    ),
    include_markdown: bool = typer.Option(
        False,
        "--include-markdown",
        help="V enterprise režimu ingestuje i markdown exporty jako fallback zdroj.",
    ),
    reclassify_metadata_only: bool = typer.Option(
        False,
        "--reclassify-metadata",
        help="Přepočítá category/pricing_type metadata v BM25 store a Qdrant payload bez re-embeddingu.",
    ),
    extract_pricing: bool = typer.Option(
        True,
        "--extract-pricing/--no-extract-pricing",
        help="V enterprise režimu extrahuje structured pricing rows do data/pricing/pricing_rows.jsonl přes pdfplumber.",
    ),
    pricing_max_pages: int = typer.Option(
        config.PRICING_EXTRACT_MAX_PAGES_PER_PDF,
        "--pricing-max-pages",
        help="Maximální počet stran na PDF pro structured pricing extraction; 0 = bez limitu.",
    ),
) -> None:
    """
    Spustí ingestion pipeline pro Raiffeisenbank dokumenty.

    Výchozí chování je incremental – přidává pouze nové dokumenty
    (detekuje duplikáty pomocí chunk_id). Existující kolekce se nesmaže.
    Použijte --full pro kompletní reindexaci od nuly.
    """
    start_time = time.time()
    documents_count = 0

    if reclassify_metadata_only:
        console.print(Panel.fit("[bold cyan]Metadata reclassification[/bold cyan]\nBM25 docs store + Qdrant payload bez re-embeddingu", border_style="cyan"))
        stats = reclassify_metadata()
        console.print(f"[green]✓[/green] Reclassified chunks: {stats.get('updated', 0)} | Qdrant payloads: {stats.get('qdrant_updated', 0)}")
        if stats.get("error"):
            console.print(f"[red]{stats['error']}[/red]")
            raise typer.Exit(code=1)
        return

    mode_label = "[red]FULL reindexace[/red]" if full else "[green]Incremental[/green]"
    if resume and not full:
        console.print("[yellow]--resume má efekt pouze s --full; pokračuji v incremental režimu bez resume.[/yellow]")
    console.print(
        Panel.fit(
            "[bold cyan]RAG Banking Chatbot – Ingestion Pipeline[/bold cyan]\n"
            f"Raiffeisenbank dokumenty → Qdrant + BM25  |  Režim: {mode_label}",
            border_style="cyan",
        )
    )

    if enterprise:
        console.print("\n[bold]Enterprise ingestion: structured JSON/Markdown + PDF semantic chunks…[/bold]")
        if extract_pricing:
            console.print("[bold]Structured pricing extraction: PDF tabulky → JSONL…[/bold]")
            pricing_stats = extract_pricing_rows_from_dir(
                documents_dir,
                config.PRICING_ROWS_PATH,
                max_pages_per_pdf=pricing_max_pages or None,
            )
            console.print(f"[green]✓[/green] Structured pricing rows: {pricing_stats['rows']} → {pricing_stats['output_path']}")
        chunks = build_enterprise_chunks(
            include_structured=True,
            include_markdown=include_markdown,
            include_pdfs=True,
            structured_dir=structured_dir,
            pdf_dir=documents_dir,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )
        if not chunks:
            console.print("[red]✗ Enterprise ingestion nevytvořil žádné chunky.[/red]")
            raise typer.Exit(code=1)
        documents_count = len({c.metadata.get("source") for c in chunks})
        console.print(f"[green]✓[/green] Enterprise chunky: {len(chunks)} ze zdrojů: {documents_count}")
    else:
        # ── Krok 1: Stažení PDF ──────────────────────────────────────────────
        if not skip_download:
            if urls_file and urls_file.exists():
                urls = load_urls_from_file(urls_file)
                console.print(f"[dim]Načteno {len(urls)} URL ze souboru {urls_file}[/dim]")
            else:
                default_sources = config.DATA_DIR / "sources.txt"
                if default_sources.exists():
                    urls = load_urls_from_file(default_sources)
                    console.print(f"[dim]Načteno {len(urls)} URL z {default_sources}[/dim]")
                else:
                    urls = config.DEFAULT_PDF_URLS
                    console.print(f"[dim]Používám {len(urls)} URL z config.py[/dim]")

            if not urls:
                console.print("[yellow]Žádné URL k stažení. Přidejte URL do data/sources.txt nebo config.DEFAULT_PDF_URLS[/yellow]")
            else:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                    progress.add_task("Stahuji PDF dokumenty…", total=None)
                    downloaded = download_all(urls, pdf_dir)
                console.print(f"[green]✓[/green] Staženo {len(downloaded)} PDF souborů")
        else:
            console.print("[dim]Přeskočeno stahování (--skip-download)[/dim]")

        console.print("\n[bold]Parsování PDF dokumentů…[/bold]")
        documents = parse_all_pdfs(pdf_dir)
        if not documents:
            console.print(f"[red]✗ Žádné dokumenty nenalezeny v '{pdf_dir}'.\nUjistěte se, že adresář obsahuje .pdf soubory.[/red]")
            raise typer.Exit(code=1)
        console.print(f"[green]✓[/green] Extrahováno {len(documents)} stránek")
        documents_count = len(documents)

        console.print("\n[bold]Chunking dokumentů…[/bold]")
        chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        console.print(f"[green]✓[/green] Vytvořeno {len(chunks)} chunků")

    # ── Krok 4: Indexace ─────────────────────────────────────────────────────
    mode_str = "FULL reindexace" if full else "Incremental (přidávám nové)"
    console.print(f"\n[bold]Indexace do Qdrant + BM25 [{mode_str}]…[/bold]")
    console.print(
        f"[dim]Qdrant: {config.QDRANT_HOST}:{config.QDRANT_PORT} "
        f"/ {config.QDRANT_COLLECTION}[/dim]"
    )
    console.print(
        f"[dim]Embedding backend: {config.EMBEDDING_BACKEND} | "
        f"model: {config.get_active_embed_model()} | dim: {config.QDRANT_VECTOR_SIZE}[/dim]"
    )

    elapsed = time.time() - start_time

    if full:
        run_full_indexing(chunks, resume=resume)
        console.print(
            Panel.fit(
                f"[bold green]✓ Full indexace dokončena za {elapsed:.1f}s[/bold green]\n"
                f"  Dokumentů/zdrojů: {documents_count} → {len(chunks)} chunků\n"
                f"  Qdrant: '{config.QDRANT_COLLECTION}' ({len(chunks)} vektorů)\n"
                f"  BM25: {config.BM25_INDEX_PATH}",
                border_style="green",
            )
        )
    else:
        stats = run_incremental_indexing(chunks)
        console.print(
            Panel.fit(
                f"[bold green]✓ Incremental indexace dokončena za {elapsed:.1f}s[/bold green]\n"
                f"  Zpracováno chunků:  {len(chunks)}\n"
                f"  Nově indexováno:   [green]{stats['new']}[/green]\n"
                f"  Přeskočeno (dup.): [dim]{stats['skipped']}[/dim]\n"
                f"  Qdrant celkem:     {stats['total_qdrant']} bodů\n"
                f"  BM25 celkem:       {stats['total_bm25']} dokumentů",
                border_style="green",
            )
        )


if __name__ == "__main__":
    app()

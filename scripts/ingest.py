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
  python scripts/ingest.py --pdf-dir data/raw

  # Přeskočení stahování (re-indexace existujících PDF)
  python scripts/ingest.py --skip-download
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
from src.ingestion.indexer import run_full_indexing
from src.ingestion.parser import parse_all_pdfs
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
) -> None:
    """
    Spustí kompletní ingestion pipeline pro Raiffeisenbank dokumenty.
    """
    start_time = time.time()

    console.print(
        Panel.fit(
            "[bold cyan]RAG Banking Chatbot – Ingestion Pipeline[/bold cyan]\n"
            "Raiffeisenbank dokumenty → Qdrant + BM25",
            border_style="cyan",
        )
    )

    # ── Krok 1: Stažení PDF ──────────────────────────────────────────────────
    if not skip_download:
        if urls_file and urls_file.exists():
            urls = load_urls_from_file(urls_file)
            console.print(f"[dim]Načteno {len(urls)} URL ze souboru {urls_file}[/dim]")
        else:
            # Hledáme i default sources.txt v data/
            default_sources = config.DATA_DIR / "sources.txt"
            if default_sources.exists():
                urls = load_urls_from_file(default_sources)
                console.print(f"[dim]Načteno {len(urls)} URL z {default_sources}[/dim]")
            else:
                urls = config.DEFAULT_PDF_URLS
                console.print(
                    f"[dim]Používám {len(urls)} URL z config.py[/dim]"
                )

        if not urls:
            console.print(
                "[yellow]Žádné URL k stažení. "
                "Přidejte URL do data/sources.txt nebo config.DEFAULT_PDF_URLS[/yellow]"
            )
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Stahuji PDF dokumenty…", total=None)
                downloaded = download_all(urls, pdf_dir)

            console.print(
                f"[green]✓[/green] Staženo {len(downloaded)} PDF souborů"
            )
    else:
        console.print("[dim]Přeskočeno stahování (--skip-download)[/dim]")

    # ── Krok 2: Parsování PDF ────────────────────────────────────────────────
    console.print("\n[bold]Parsování PDF dokumentů…[/bold]")
    documents = parse_all_pdfs(pdf_dir)

    if not documents:
        console.print(
            f"[red]✗ Žádné dokumenty nenalezeny v '{pdf_dir}'.\n"
            "Ujistěte se, že adresář obsahuje .pdf soubory.[/red]"
        )
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Extrahováno {len(documents)} stránek")

    # ── Krok 3: Chunking ─────────────────────────────────────────────────────
    console.print("\n[bold]Chunking dokumentů…[/bold]")
    chunks = chunk_documents(
        documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    console.print(f"[green]✓[/green] Vytvořeno {len(chunks)} chunků")

    # ── Krok 4: Indexace ─────────────────────────────────────────────────────
    console.print("\n[bold]Indexace do Qdrant + BM25…[/bold]")
    console.print(
        f"[dim]Qdrant: {config.QDRANT_HOST}:{config.QDRANT_PORT} "
        f"/ {config.QDRANT_COLLECTION}[/dim]"
    )
    console.print(f"[dim]Embed model: {config.EMBED_MODEL} (Ollama)[/dim]")

    run_full_indexing(chunks)

    elapsed = time.time() - start_time
    console.print(
        Panel.fit(
            f"[bold green]✓ Ingestion dokončena za {elapsed:.1f}s[/bold green]\n"
            f"  Dokumentů: {len(documents)} stránek → {len(chunks)} chunků\n"
            f"  Qdrant: '{config.QDRANT_COLLECTION}' ({len(chunks)} vektorů)\n"
            f"  BM25: {config.BM25_INDEX_PATH}",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()

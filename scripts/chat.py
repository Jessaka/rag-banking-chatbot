#!/usr/bin/env python3
"""
Interaktivní CLI chatbot pro Raiffeisenbank RAG systém.

Funkce:
  - Konverzační mód s pamětí
  - Zobrazení zdrojů pro každou odpověď
  - Příkazy: /help, /reset, /sources, /quit, /debug

Použití:
  python scripts/chat.py
  python scripts/chat.py --no-history     # Bez konverzační paměti
  python scripts/chat.py --show-sources   # Vždy zobrazí zdroje
  python scripts/chat.py --debug          # Zobrazí retrieval metadata
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generation.chain import BankingRAGChain
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)

# CLI příkazy
COMMANDS = {
    "/help": "Zobrazí tuto nápovědu",
    "/reset": "Vymaže konverzační historii",
    "/sources": "Přepne zobrazení zdrojů on/off",
    "/debug": "Přepne debug mód (retrieval metadata)",
    "/quit": "Ukončí chatbot",
    "/exit": "Ukončí chatbot",
}


def _print_welcome() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]Raiffeisenbank AI Asistent[/bold cyan]\n"
            "[dim]Powered by Mistral 7B + RAG (Qdrant + BM25 + BGE Reranker)[/dim]\n\n"
            "Zadejte dotaz v češtině nebo napište [bold]/help[/bold] pro nápovědu.",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _print_help() -> None:
    table = Table(title="Dostupné příkazy", border_style="dim")
    table.add_column("Příkaz", style="cyan", no_wrap=True)
    table.add_column("Popis")
    for cmd, desc in COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


def _print_sources(sources: list, debug: bool = False) -> None:
    if not sources:
        return

    table = Table(
        title=f"Použité zdroje ({len(sources)})",
        border_style="dim",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Dokument", style="cyan")
    table.add_column("Strana", justify="right", width=6)
    if debug:
        table.add_column("Hybrid", justify="right", width=8)
        table.add_column("Rerank", justify="right", width=8)

    for i, doc in enumerate(sources, start=1):
        row = [
            str(i),
            doc.metadata.get("file_name", "?"),
            str(doc.metadata.get("page", "?")),
        ]
        if debug:
            row.append(f"{doc.metadata.get('hybrid_score', '–'):.4f}"
                       if "hybrid_score" in doc.metadata else "–")
            row.append(f"{doc.metadata.get('rerank_score', '–'):.4f}"
                       if "rerank_score" in doc.metadata else "–")
        table.add_row(*row)

    console.print(table)


@app.command()
def main(
    no_history: bool = typer.Option(
        False, "--no-history", help="Deaktivuje konverzační paměť."
    ),
    show_sources: bool = typer.Option(
        False, "--show-sources", "-s", help="Vždy zobrazí zdroje po odpovědi."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Zobrazí retrieval metadata."
    ),
) -> None:
    """
    Interaktivní RAG chatbot pro dotazy na Raiffeisenbank dokumenty.
    """
    _print_welcome()

    try:
        chain = BankingRAGChain(conversational=not no_history)
    except Exception as exc:
        console.print(
            f"[red]✗ Chyba při inicializaci: {exc}\n"
            "Ujistěte se, že Ollama a Qdrant běží a data jsou indexována.[/red]"
        )
        raise typer.Exit(code=1)

    show_sources_flag = show_sources
    debug_flag = debug

    while True:
        try:
            # Uživatelský vstup
            console.print()
            user_input = console.input("[bold blue]Vy:[/bold blue] ").strip()

            if not user_input:
                continue

            # ── Zpracování příkazů ──────────────────────────────────────────
            if user_input.lower() in ("/quit", "/exit"):
                console.print("[dim]Na shledanou![/dim]")
                break

            if user_input.lower() == "/help":
                _print_help()
                continue

            if user_input.lower() == "/reset":
                chain.reset_history()
                console.print("[green]✓[/green] Konverzační historie vymazána")
                continue

            if user_input.lower() == "/sources":
                show_sources_flag = not show_sources_flag
                status = "zapnuto" if show_sources_flag else "vypnuto"
                console.print(f"[dim]Zobrazení zdrojů: {status}[/dim]")
                continue

            if user_input.lower() == "/debug":
                debug_flag = not debug_flag
                status = "zapnut" if debug_flag else "vypnut"
                console.print(f"[dim]Debug mód: {status}[/dim]")
                continue

            # ── Dotaz na RAG chain ──────────────────────────────────────────
            with console.status(
                "[dim]Hledám v dokumentech a generuji odpověď…[/dim]",
                spinner="dots",
            ):
                result = chain.ask(user_input)

            answer = result["answer"]
            sources = result["sources"]
            rewritten = result["rewritten_query"]

            # Zobrazení přeformulovaného dotazu (pouze pokud se liší)
            if debug_flag and rewritten != user_input:
                console.print(
                    f"[dim]Přeformulovaný dotaz: {rewritten}[/dim]"
                )

            # Odpověď
            console.print()
            console.print(Text("Asistent:", style="bold green"))
            console.print(Markdown(answer))

            # Zdroje
            if show_sources_flag or debug_flag:
                console.print()
                _print_sources(sources, debug=debug_flag)

        except KeyboardInterrupt:
            console.print("\n[dim]Přerušeno (Ctrl+C). Na shledanou![/dim]")
            break
        except Exception as exc:
            console.print(f"[red]Chyba: {exc}[/red]")
            if debug_flag:
                console.print_exception()


if __name__ == "__main__":
    app()

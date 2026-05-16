#!/usr/bin/env python3
"""
Spuštění FastAPI serveru přes uvicorn.

Použití:
  python scripts/serve.py                        # výchozí: localhost:8000
  python scripts/serve.py --host 0.0.0.0         # dostupné v síti
  python scripts/serve.py --port 9000            # jiný port
  python scripts/serve.py --reload               # hot-reload pro vývoj
  python scripts/serve.py --workers 2            # více workerů (prod)

Poznámka: --reload a --workers nelze kombinovat.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
import uvicorn

sys.path.insert(0, str(Path(__file__).parent.parent))

app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def main(
    host: str = typer.Option(
        "127.0.0.1",
        "--host", "-h",
        help="Hostname / IP adresa pro naslouchání.",
    ),
    port: int = typer.Option(
        8000,
        "--port", "-p",
        help="TCP port.",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Hot-reload při změně souborů (pouze pro vývoj).",
    ),
    workers: int = typer.Option(
        1,
        "--workers", "-w",
        help="Počet uvicorn workerů. Ignorováno pokud je --reload aktivní.",
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Úroveň logování: debug | info | warning | error.",
    ),
) -> None:
    """
    Spustí Raiffeisenbank RAG API server.
    """
    if reload and workers > 1:
        typer.echo(
            "⚠  --reload a --workers nelze kombinovat. Spouštím s --reload, workers=1.",
            err=True,
        )
        workers = 1

    typer.echo(f"Spouštím API na http://{host}:{port}")
    typer.echo(f"  Swagger UI:  http://{host}:{port}/docs")
    typer.echo(f"  ReDoc:       http://{host}:{port}/redoc")
    typer.echo(f"  Workers: {workers} | Reload: {reload} | Log: {log_level}")

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level=log_level,
        access_log=True,
    )


if __name__ == "__main__":
    app()

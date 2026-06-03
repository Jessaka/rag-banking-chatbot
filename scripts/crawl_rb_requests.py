#!/usr/bin/env python3
"""Lightweight rb.cz crawler using requests + BeautifulSoup (no Playwright).

Fallback pro prostředí kde Playwright není podporován.
Výstup: data/crawl/structured/*.json (stejný formát jako crawl_rb.py).

Použití:
    python3 scripts/crawl_rb_requests.py --max-pages 2000 --depth 4
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
import typer
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

console = Console()

BASE_URL = "https://www.rb.cz"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
CRAWL_DIR = config.DATA_DIR / "crawl"
STRUCTURED_DIR = CRAWL_DIR / "structured"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "cs-CZ,cs;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".doc", ".docx", ".xls", ".xlsx")
SKIP_PREFIXES = (
    "/en/", "/uk/",
    "/o-nas/kariera", "/attachments/kariera",
    "/o-nas/media", "/o-nas/pro-media", "/o-nas/tiskove-zpravy",
    "/o-nas/vyrocni-zpravy", "/o-nas/investor", "/o-nas/vedeni-banky",
    "/promo/", "/test/",
)


@dataclass
class Stats:
    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    outputs: list[Path] = field(default_factory=list)


def normalize_url(url: str, base: str = BASE_URL) -> str:
    full = urljoin(base, url)
    p = urlparse(full)
    return urlunparse((p.scheme or "https", p.netloc.lower(), re.sub(r"/{2,}", "/", p.path).rstrip("/") or "/", "", "", ""))


def is_rb_url(url: str) -> bool:
    p = urlparse(url)
    if p.netloc.lower() not in {"rb.cz", "www.rb.cz"}:
        return False
    if any(p.path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    return not p.path.lower().endswith(SKIP_EXTENSIONS)


def safe_slug(url: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_")
    h = hashlib.sha256(url.encode()).hexdigest()[:8]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", path)[:60]
    return f"{slug}_{h}" if slug else h


def extract_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["nav", "footer", "script", "style", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        norm = normalize_url(href, base_url)
        if is_rb_url(norm):
            links.append(norm)
    return list(dict.fromkeys(links))


def load_sitemap() -> list[str]:
    try:
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        return sorted({normalize_url(loc.get_text(strip=True)) for loc in soup.find_all("loc") if is_rb_url(normalize_url(loc.get_text(strip=True)))})
    except Exception as exc:
        console.print(f"[yellow]Sitemap selhala: {exc}[/yellow]")
        return []


def load_robots() -> RobotFileParser:
    """Parse robots.txt manually — Python's RobotFileParser has issues with some servers."""
    rp = RobotFileParser()
    try:
        resp = requests.get(f"{BASE_URL}/robots.txt", headers=HEADERS, timeout=10)
        rp.parse(resp.text.splitlines())
    except Exception:
        pass
    return rp


def fetch(session: requests.Session, url: str) -> tuple[str, int]:
    resp = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    return resp.text, resp.status_code


def crawl(start_url: str | None, max_pages: int, depth: int) -> Stats:
    CRAWL_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)
    stats = Stats()
    robots = load_robots()
    seeds = [normalize_url(start_url)] if start_url else load_sitemap()
    console.print(f"[green]Seeds: {len(seeds)} URLs from {'URL' if start_url else 'sitemap'}[/green]")

    q: deque[tuple[str, int]] = deque((u, 0) for u in seeds[:max_pages])
    seen: set[str] = set(u for u, _ in q)
    sess = requests.Session()

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), console=console) as progress:
        task = progress.add_task("Crawluji rb.cz…", total=max_pages)

        while q and stats.crawled < max_pages:
            url, d = q.popleft()

            if not robots.can_fetch(USER_AGENT, url):
                stats.skipped += 1
                continue

            try:
                html, status = fetch(sess, url)
            except Exception as exc:
                console.print(f"[red]FAIL {url}: {exc}[/red]")
                stats.failed += 1
                continue

            if status >= 400:
                stats.skipped += 1
                continue

            soup = BeautifulSoup(html, "html.parser")
            title = (soup.find("title") or soup.find("h1") or type("", (), {"get_text": lambda *a, **k: url})()).get_text(strip=True)
            body_text = extract_text(BeautifulSoup(html, "html.parser"))

            if len(body_text) < 150:
                stats.skipped += 1
                continue

            slug = safe_slug(url)
            out_path = STRUCTURED_DIR / f"{slug}.json"
            payload = {
                "url": url,
                "title": title,
                "content": body_text[:12000],
                "metadata": {
                    "crawled_at": datetime.now(timezone.utc).isoformat(),
                    "depth": d,
                    "status_code": status,
                    "content_length": len(body_text),
                },
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            stats.outputs.append(out_path)
            stats.crawled += 1
            progress.update(task, advance=1, description=f"[cyan]{url[-60:]}[/cyan]")

            if d < depth:
                links = extract_links(BeautifulSoup(html, "html.parser"), url)
                for link in links:
                    if link not in seen and stats.crawled + len(q) < max_pages * 2:
                        seen.add(link)
                        q.append((link, d + 1))

            time.sleep(0.3)

    return stats


app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def main(
    url: str = typer.Option(None, "--url", help="Start URL. Bez tohoto parametru se použije sitemap."),
    max_pages: int = typer.Option(2000, "--max-pages", "-m"),
    depth: int = typer.Option(4, "--depth", "-d"),
) -> None:
    console.print(f"[bold]Crawl: max_pages={max_pages} depth={depth}[/bold]")
    stats = crawl(url, max_pages=max_pages, depth=depth)
    console.print(f"[green]Hotovo: crawled={stats.crawled} skipped={stats.skipped} failed={stats.failed}[/green]")
    console.print(f"[green]Výstup: {STRUCTURED_DIR} ({len(stats.outputs)} souborů)[/green]")


if __name__ == "__main__":
    app()

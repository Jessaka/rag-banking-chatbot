#!/usr/bin/env python3
"""Enterprise crawler pro rb.cz → raw HTML + structured JSON/Markdown.

Použití:
  python3 scripts/crawl_rb.py --max-pages 50 --depth 2
  python3 scripts/crawl_rb.py --url https://www.rb.cz/osobni/ucty/aktivni-ucet --depth 0

Pozn.: vyžaduje Playwright Chromium (`playwright install chromium`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
import typer
from bs4 import BeautifulSoup, Tag
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)

BASE_URL = "https://www.rb.cz"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
CRAWL_DIR = config.DATA_DIR / "crawl"
RAW_HTML_DIR = CRAWL_DIR / "raw_html"
STRUCTURED_DIR = CRAWL_DIR / "structured"
CRAWL_LOG = CRAWL_DIR / "crawl_log.jsonl"

USER_AGENT = "Mozilla/5.0 (compatible; RAG-Banking-Enterprise-Crawler/1.0; rb.cz RAG dataset)"
SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".doc", ".docx", ".xls", ".xlsx")
SKIP_PREFIXES = ("/en/", "/uk/", "/o-nas/kariera", "/attachments/kariera", "/promo/", "/test/")
PRICING_KEYWORDS = ("sazebník", "sazebnik", "ceník", "cenik", "fee", "price", "poplatek", "poplatky", "kč", "czk", "zdarma")


@dataclass
class CrawlStats:
    queued: int = 0
    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    discovered_links: int = 0
    outputs: list[Path] = field(default_factory=list)


def _normalize_url(url: str, base: str = BASE_URL) -> str:
    full = urljoin(base, url)
    p = urlparse(full)
    return urlunparse((p.scheme or "https", p.netloc.lower(), re.sub(r"/{2,}", "/", p.path).rstrip("/") or "/", "", "", ""))


def _is_rb_html_url(url: str) -> bool:
    p = urlparse(url)
    if p.netloc.lower() not in {"rb.cz", "www.rb.cz"}:
        return False
    if any(p.path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    return not p.path.lower().endswith(SKIP_EXTENSIONS)


def _safe_slug(url: str) -> str:
    p = urlparse(url)
    raw = (p.netloc + p.path).strip("/").replace("/", "_") or "index"
    slug = re.sub(r"[^\w.-]+", "_", raw)[:100]
    return f"{slug}_{hashlib.sha256(url.encode()).hexdigest()[:10]}"


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _category_for(url: str, title: str = "") -> str:
    hay = f"{url} {title}".lower()
    rules = {
        "accounts": ["ucty", "ucet", "účet"],
        "cards": ["karty", "karta", "kreditni", "debetni"],
        "mortgages": ["hypotek", "hypote"],
        "loans": ["pujck", "půjčk", "uver", "úvěr"],
        "savings": ["sporeni", "spoření", "vklad"],
        "investments": ["invest", "fond"],
        "insurance": ["pojist", "pojišt"],
        "pricing": ["cenik", "ceník", "sazebnik", "sazebník", "poplat"],
        "documents": ["dokument", "podmink", "podmínk"],
        "security": ["bezpec", "bezpeč", "phishing"],
    }
    for category, needles in rules.items():
        if any(n in hay for n in needles):
            return category
    return "general"


def _document_type(url: str, title: str, text: str) -> str:
    hay = f"{url} {title} {text[:2000]}".lower()
    if any(k in hay for k in PRICING_KEYWORDS[:7]):
        return "pricing"
    if "faq" in hay or "časté dotazy" in hay or "caste-dotazy" in hay:
        return "faq"
    if "podmín" in hay or "podmink" in hay or "vop" in hay:
        return "terms"
    if "/osobni/" in url or "/podnikatele/" in url:
        return "product_page"
    return "article"


def _table_to_struct(table: Tag, order: int, section_title: str = "") -> dict | None:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    headers = rows[0]
    md = [" | ".join(headers), " | ".join(["---"] * width)]
    md.extend(" | ".join(r) for r in rows[1:])
    return {"caption": "", "section_title": section_title, "headers": headers, "rows": rows[1:], "markdown": "\n".join(md), "order": order}


def _extract_structured(html: str, url: str) -> tuple[dict, str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    for sel in ["script", "style", "noscript", "svg", "app-navigation", "app-header", "app-footer", "nav", "header", "footer"]:
        for tag in soup.select(sel):
            tag.decompose()

    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical_url = _normalize_url(canonical.get("href"), url) if canonical and canonical.get("href") else url
    title = _clean_text((soup.find("h1") or soup.find("title") or soup.new_tag("span")).get_text(" ", strip=True)) or canonical_url

    main = soup.select_one("main, [role='main'], article, .page-wrapper, .content, app-root") or soup.body or soup
    headings = main.find_all(re.compile(r"^h[1-6]$"))
    sections: list[dict] = []
    current = {"heading": title, "level": 1, "content": [], "anchor": "", "order": 0}
    order = 0

    def flush() -> None:
        nonlocal current
        content = _clean_text("\n\n".join(current["content"]))
        if content or current["heading"]:
            sections.append({**current, "content": content})

    content_tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "blockquote"]
    for el in main.find_all(content_tags):
        text = _clean_text(el.get_text(" ", strip=True))
        if not text:
            continue
        if re.match(r"^h[1-6]$", el.name or ""):
            if current["content"]:
                flush()
            order += 1
            current = {"heading": text, "level": int(el.name[1]), "content": [], "anchor": el.get("id", ""), "order": order}
        else:
            current["content"].append(text)
    flush()

    tables = []
    for idx, table in enumerate(main.find_all("table")):
        section_title = sections[-1]["heading"] if sections else title
        parsed = _table_to_struct(table, idx, section_title)
        if parsed:
            tables.append(parsed)

    faq = []
    for idx, detail in enumerate(main.find_all("details")):
        summary = detail.find("summary")
        question = _clean_text(summary.get_text(" ", strip=True)) if summary else ""
        if summary:
            summary.extract()
        answer = _clean_text(detail.get_text(" ", strip=True))
        if question and answer:
            faq.append({"question": question, "answer": answer, "section_title": title, "order": idx})
    for idx, panel in enumerate(main.select("mat-expansion-panel, [class*='accordion'], [class*='faq']"), start=len(faq)):
        texts = [_clean_text(t.get_text(" ", strip=True)) for t in panel.find_all(["h2", "h3", "h4", "button", "p", "li"])]
        texts = [t for t in texts if t]
        if len(texts) >= 2:
            faq.append({"question": texts[0], "answer": _clean_text(" ".join(texts[1:])), "section_title": title, "order": idx})

    cards = []
    for idx, card in enumerate(main.select("[class*='card'], [class*='product-box'], [class*='benefit'], [class*='cta']")):
        text = _clean_text(card.get_text(" ", strip=True))
        if len(text) > 20:
            cards.append({"title": text.split(". ")[0][:120], "content": text, "order": idx})

    full_text = _clean_text(main.get_text("\n", strip=True))
    metadata = {
        "source_type": "web",
        "document_type": _document_type(canonical_url, title, full_text),
        "category": _category_for(canonical_url, title),
        "language": "cs",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "canonical_url": canonical_url,
        "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
        "pricing_detected": any(k in full_text.lower() for k in PRICING_KEYWORDS),
    }
    page = {"url": canonical_url, "title": title, "sections": sections, "tables": tables, "faq": faq, "cards": cards, "metadata": metadata}

    markdown_parts = [f"# {title}", f"Zdroj: {canonical_url}", ""]
    for sec in sections:
        heading = "#" * min(max(sec["level"], 2), 6)
        markdown_parts.extend([f"{heading} {sec['heading']}", sec["content"], ""])
    for table in tables:
        markdown_parts.extend([f"## Tabulka: {table.get('caption') or table.get('section_title') or title}", table["markdown"], ""])
    for item in faq:
        markdown_parts.extend([f"## FAQ: {item['question']}", item["answer"], ""])
    page["markdown"] = _clean_text("\n\n".join(markdown_parts))

    links = []
    for a in soup.find_all("a", href=True):
        link = _normalize_url(a["href"], canonical_url)
        if _is_rb_html_url(link):
            links.append(link)
    return page, page["markdown"], sorted(set(links))


async def _expand_and_render(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        await page.wait_for_timeout(2_000)
    for y in range(0, 10000, 600):
        await page.evaluate("y => window.scrollTo(0, y)", y)
        await page.wait_for_timeout(250)
        height = await page.evaluate("() => document.documentElement.scrollHeight")
        if y >= height:
            break
    for selector in ["[role='tab']", "mat-expansion-panel-header", "summary", "[aria-expanded='false']", "button:has-text('Zobrazit více')"]:
        loc = page.locator(selector)
        try:
            count = await loc.count()
            for i in range(min(count, 80)):
                try:
                    if await loc.nth(i).is_visible(timeout=300):
                        await loc.nth(i).click(timeout=500)
                        await page.wait_for_timeout(150)
                except Exception:
                    pass
        except Exception:
            pass
    return await page.content()


def _load_robots() -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url(ROBOTS_URL)
    try:
        resp = requests.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        rp.parse(resp.text.splitlines())
    except Exception as exc:
        logger.warning(f"Nelze načíst robots.txt: {exc}")
    return rp


def _load_sitemap_urls() -> list[str]:
    try:
        resp = requests.get(SITEMAP_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        return sorted({_normalize_url(loc.get_text(strip=True)) for loc in soup.find_all("loc") if _is_rb_html_url(_normalize_url(loc.get_text(strip=True)))})
    except Exception as exc:
        logger.warning(f"Sitemap selhala: {exc}")
        return []


async def crawl(start_url: str | None, max_pages: int, depth: int, headed: bool) -> CrawlStats:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright není nainstalovaný. Spusťte: pip install playwright && playwright install chromium") from exc

    CRAWL_DIR.mkdir(parents=True, exist_ok=True)
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)
    stats = CrawlStats()
    robots = _load_robots()
    seeds = [_normalize_url(start_url)] if start_url else _load_sitemap_urls()
    q: deque[tuple[str, int]] = deque((u, 0) for u in seeds[:max_pages])
    seen: set[str] = set()
    stats.queued = len(q)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, args=["--no-sandbox"])
        context = await browser.new_context(locale="cs-CZ", user_agent=USER_AGENT, viewport={"width": 1365, "height": 900})
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,mp4,webp}", lambda route: route.abort())

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn(), console=console) as progress:
            task = progress.add_task("Crawluji rb.cz…", total=max_pages)
            while q and stats.crawled < max_pages:
                url, d = q.popleft()
                if url in seen or not _is_rb_html_url(url):
                    continue
                seen.add(url)
                if not robots.can_fetch(USER_AGENT, url):
                    stats.skipped += 1
                    continue
                progress.update(task, advance=1, description=f"[dim]{urlparse(url).path[:60]}[/dim]")
                try:
                    html = await _expand_and_render(page, url)
                    structured, markdown, links = _extract_structured(html, url)
                    canonical = structured["url"]
                    slug = _safe_slug(canonical)
                    raw_path = RAW_HTML_DIR / f"{slug}.html"
                    json_path = STRUCTURED_DIR / f"{slug}.json"
                    md_path = STRUCTURED_DIR / f"{slug}.md"
                    raw_path.write_text(html, encoding="utf-8")
                    json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
                    md_path.write_text(markdown, encoding="utf-8")
                    with CRAWL_LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"url": url, "canonical_url": canonical, "depth": d, "json": str(json_path), "raw_html": str(raw_path), "crawled_at": structured["metadata"]["crawled_at"], "link_count": len(links)}, ensure_ascii=False) + "\n")
                    stats.crawled += 1
                    stats.outputs.append(json_path)
                    if d < depth:
                        for link in links:
                            if link not in seen:
                                q.append((link, d + 1))
                        stats.discovered_links += len(links)
                except Exception as exc:
                    stats.failed += 1
                    logger.warning(f"Crawl selhal {url}: {str(exc)[:160]}")
        await context.close()
        await browser.close()
    return stats


@app.command()
def main(
    url: str = typer.Option(None, "--url", help="Volitelná start URL. Pokud není zadána, použije se sitemap.xml."),
    max_pages: int = typer.Option(200, "--max-pages", "-m", help="Maximální počet stránek."),
    depth: int = typer.Option(2, "--depth", "-d", help="Maximální interní crawl depth ze seed URL."),
    headed: bool = typer.Option(False, "--headed", help="Spustí viditelný browser."),
) -> None:
    console.print(Panel.fit("[bold cyan]RB Enterprise Structured Crawler[/bold cyan]\nraw_html + structured JSON/Markdown", border_style="cyan"))
    try:
        stats = asyncio.run(crawl(url, max_pages=max_pages, depth=depth, headed=headed))
    except Exception as exc:
        console.print(f"[red]✗ Crawl selhal: {str(exc)[:240]}[/red]")
        raise typer.Exit(code=1)
    table = Table(title="Crawl výsledky", border_style="green")
    table.add_column("Metrika")
    table.add_column("Hodnota", justify="right")
    table.add_row("Crawled", str(stats.crawled))
    table.add_row("Skipped", str(stats.skipped))
    table.add_row("Failed", str(stats.failed))
    table.add_row("Discovered links", str(stats.discovered_links))
    table.add_row("Structured JSON", str(len(stats.outputs)))
    console.print(table)
    console.print(f"Výstup: [cyan]{STRUCTURED_DIR}[/cyan] | Log: [cyan]{CRAWL_LOG}[/cyan]")


if __name__ == "__main__":
    app()

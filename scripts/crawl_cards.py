#!/usr/bin/env python3
"""Scrape credit/payment card product pages from rb.cz and index them.

Saves to data/raw/playwright_karty_*.txt (same format as playwright_hypoteky_*.txt),
then indexes with category=cards, document_type=product_page.
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from src.ingestion.chunker import chunk_documents
from src.ingestion.indexer import run_incremental_indexing
from src.utils.logger import get_logger

logger = get_logger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
TODAY = date.today().isoformat()
USER_AGENT = "Mozilla/5.0 (compatible; RAG-Banking-Enterprise-Crawler/1.0; rb.cz RAG dataset)"

CARD_URLS = [
    "https://www.rb.cz/osobni/kreditni-karty",
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty",
    "https://www.rb.cz/osobni/platebni-karty",
]


def _url_to_filename(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^\w-]+", "_", path).strip("_")
    return f"playwright_karty_{slug}.txt"


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


async def _render_page(url: str) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            locale="cs-CZ",
            user_agent=USER_AGENT,
            viewport={"width": 1365, "height": 900},
        )
        page = await context.new_page()
        await page.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,mp4,webp}",
            lambda route: route.abort(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            await page.wait_for_timeout(2_000)

        # Scroll to trigger lazy-loaded content
        for y in range(0, 8000, 600):
            await page.evaluate("y => window.scrollTo(0, y)", y)
            await page.wait_for_timeout(200)
            height = await page.evaluate("() => document.documentElement.scrollHeight")
            if y >= height:
                break

        # Expand accordions / tabs
        for selector in [
            "[role='tab']",
            "mat-expansion-panel-header",
            "summary",
            "[aria-expanded='false']",
            "button:has-text('Zobrazit více')",
        ]:
            loc = page.locator(selector)
            try:
                count = await loc.count()
                for i in range(min(count, 40)):
                    try:
                        if await loc.nth(i).is_visible(timeout=300):
                            await loc.nth(i).click(timeout=500)
                            await page.wait_for_timeout(150)
                    except Exception:
                        pass
            except Exception:
                pass

        html = await page.content()
        await context.close()
        await browser.close()
        return html


def _extract_text(html: str, url: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for sel in [
        "script", "style", "noscript", "svg",
        "app-navigation", "app-header", "app-footer",
        "nav", "header", "footer",
    ]:
        for tag in soup.select(sel):
            tag.decompose()

    main = (
        soup.select_one("main, [role='main'], article, .page-wrapper, .content, app-root")
        or soup.body
        or soup
    )
    return _clean(main.get_text("\n", strip=True))


def _check_404(text: str) -> bool:
    return any(s in text.lower() for s in [
        "stránka neexistuje", "stránka nebyla nalezena",
        "omlouváme se, požadovaná stránka",
        "404", "page not found",
    ])


async def scrape_all() -> list[tuple[str, str]]:
    """Returns list of (url, text) for valid pages."""
    results = []
    for url in CARD_URLS:
        logger.info(f"Scraping: {url}")
        try:
            html = await _render_page(url)
            text = _extract_text(html, url)
            if _check_404(text):
                logger.warning(f"404 detected: {url}")
                continue
            if len(text) < 200:
                logger.warning(f"Too short ({len(text)} chars), skipping: {url}")
                continue
            logger.info(f"  OK: {len(text)} chars")
            results.append((url, text))
        except Exception as exc:
            logger.error(f"  FAILED {url}: {exc}")
    return results


def save_txt(url: str, text: str) -> Path:
    fname = _url_to_filename(url)
    path = RAW_DIR / fname
    content = (
        f"URL: {url}\n"
        f"Kategorie: cards\n"
        f"Datum: {TODAY}\n"
        f"Zdroj: Playwright (JS-rendered)\n"
        "\n"
        "============================================================\n"
        f"{text}\n"
    )
    path.write_text(content, encoding="utf-8")
    logger.info(f"Saved: {path}")
    return path


def index_files(pages: list[tuple[str, str]]) -> dict:
    docs = []
    for url, text in pages:
        docs.append(Document(
            page_content=text,
            metadata={
                "source": url,
                "source_url": url,
                "category": "cards",
                "document_type": "product_page",
                "document_year": date.today().year,
                "language": "cs",
            },
        ))

    if not docs:
        logger.error("No documents to index.")
        return {}

    chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
    logger.info(f"Created {len(chunks)} chunks from {len(docs)} documents")
    stats = run_incremental_indexing(chunks)
    logger.info(f"Indexing complete: {stats}")
    return stats


def main():
    pages = asyncio.run(scrape_all())
    if not pages:
        logger.error("No valid pages scraped.")
        sys.exit(1)

    for url, text in pages:
        save_txt(url, text)

    stats = index_files(pages)
    print(f"\nDone: {len(pages)} pages scraped, {stats.get('new', 0)} new chunks indexed")


if __name__ == "__main__":
    main()

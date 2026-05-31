"""Build playwright_karty_*.txt from existing crawl JSONs and index them."""
from __future__ import annotations

import json
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
CRAWL_DIR = Path(__file__).resolve().parent.parent / "data" / "crawl" / "structured"
TODAY = date.today().isoformat()

# Best crawled file per canonical URL
CARD_FILES: dict[str, str] = {
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty/kreditni-karta-easy":
        "www.rb.cz_kreditni-karta-easy_178ab0601d.json",
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty/kreditni-karta-style":
        "www.rb.cz_osobni-finance_platebni-karty_kreditni-karty_style-karta_162697cd41.json",
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty/kreditni-karta-rb-premium":
        "www.rb.cz_osobni_kreditni-karty_standardni-karty_kreditni-karta-rb-premium_fb82c86de5.json",
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty/kreditni-karta-visa-gold":
        "www.rb.cz_osobni_kreditni-karty_standardni-karty_kreditni-karta-visa-gold_961a007097.json",
    "https://www.rb.cz/osobni/kreditni-karty/specialni-karty/kreditni-karta-o2":
        "www.rb.cz_osobni_kreditni-karty_o2-rb-karta_f28ac4a27b.json",
    "https://www.rb.cz/osobni/kreditni-karty/standardni-karty":
        "www.rb.cz_osobni-finance_kreditni-karty_doplnkove-informace_prehledova-tabulka-karet_b11539284a.json",
    "https://www.rb.cz/osobni/kreditni-karty":
        "www.rb.cz_osobni_kreditni-karty_kreditni-karta-mall_035c90031c.json",
}

NAV_NOISE = frozenset({
    "osobní účty", "běžný účet zdarma", "účet pro děti", "všechny účty",
    "přihlásit se", "vstup na účet", "nápověda", "vyhledat", "hledat",
    "odměna k účtu", "to chci", "mám zájem",
})


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _section_is_nav(heading: str, content: str) -> bool:
    h = heading.lower().strip()
    if h in NAV_NOISE:
        return True
    # Sections with mostly short lines (pure nav dumps)
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        return False
    avg_len = sum(len(l) for l in lines) / len(lines)
    return avg_len < 18 and len(lines) > 6


def _extract_text(json_path: Path, canonical_url: str) -> str:
    d = json.load(open(json_path))
    title = d.get("title", "")
    sections = d.get("sections", [])
    faq = d.get("faq", [])

    parts: list[str] = [title]
    seen: set[str] = set()

    for sec in sections:
        heading = sec.get("heading", "").strip()
        content = _clean(sec.get("content", ""))
        if not content:
            continue
        if _section_is_nav(heading, content):
            continue
        # Deduplicate near-identical content
        key = content[:80]
        if key in seen:
            continue
        seen.add(key)
        if heading and heading.lower() != title.lower():
            parts.append(f"\n{heading}")
        parts.append(content)

    for item in faq:
        q = item.get("question", "").strip()
        a = item.get("answer", "").strip()
        if q and a:
            parts.append(f"\nQ: {q}\nA: {a}")

    return _clean("\n\n".join(p for p in parts if p))


def _url_to_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return re.sub(r"[^\w-]+", "_", path).strip("_")


def save_txt(url: str, text: str) -> Path:
    slug = _url_to_slug(url)
    fname = f"playwright_karty_{slug}.txt"
    path = RAW_DIR / fname
    content = (
        f"URL: {url}\n"
        f"Kategorie: cards\n"
        f"Datum: {TODAY}\n"
        f"Zdroj: Crawl (existující data)\n"
        "\n"
        "============================================================\n"
        f"{text}\n"
    )
    path.write_text(content, encoding="utf-8")
    logger.info(f"Saved {path.name}: {len(text)} chars")
    return path


def main():
    pages: list[tuple[str, str]] = []

    for url, fname in CARD_FILES.items():
        fpath = CRAWL_DIR / fname
        if not fpath.exists():
            logger.warning(f"File not found: {fpath}")
            continue
        text = _extract_text(fpath, url)
        if len(text) < 100:
            logger.warning(f"Too short after extraction: {url}")
            continue
        logger.info(f"Extracted {len(text)} chars from {fname[:50]}")
        pages.append((url, text))
        save_txt(url, text)

    if not pages:
        logger.error("No pages to index.")
        sys.exit(1)

    docs = [
        Document(
            page_content=text,
            metadata={
                "source": url,
                "source_url": url,
                "category": "cards",
                "document_type": "product_page",
                "document_year": date.today().year,
                "language": "cs",
            },
        )
        for url, text in pages
    ]

    chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
    logger.info(f"Created {len(chunks)} chunks from {len(docs)} documents")
    stats = run_incremental_indexing(chunks)
    logger.info(f"Indexing complete: {stats}")
    print(f"\nDone: {len(pages)} pages, {stats.get('new', 0)} new / {stats.get('skipped', 0)} skipped chunks")


if __name__ == "__main__":
    main()

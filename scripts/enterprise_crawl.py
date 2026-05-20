#!/usr/bin/env python3
"""Produkční enterprise crawl pipeline pro rb.cz.

Funkce: nested sitemap discovery, HTML + JS rendering přes Playwright,
document discovery/download, incremental manifest, retry queue, coverage log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
import typer
from bs4 import BeautifulSoup, Tag
from rich.console import Console
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
USER_AGENT = "RAG-Banking-Enterprise-Crawler/2.0"
REQUEST_TIMEOUT = 30
PLAYWRIGHT_TIMEOUT_MS = 60_000
MAX_DEPTH = 2
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024

DISCOVERY_DIR = config.DISCOVERY_DIR
CRAWL_DIR = config.CRAWL_DIR
RAW_HTML_DIR = CRAWL_DIR / "raw_html"
STRUCTURED_DIR = CRAWL_DIR / "structured"
DOCUMENTS_DIR = config.DOCUMENTS_DIR
SITEMAPS_PATH = DISCOVERY_DIR / "sitemaps.json"
CRAWL_LOG_PATH = CRAWL_DIR / "crawl_log.jsonl"
MANIFEST_PATH = config.CRAWL_MANIFEST_PATH
DOC_METADATA_PATH = DOCUMENTS_DIR / "metadata.jsonl"

DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".xml")
SKIP_PREFIXES = ("/en/", "/uk/", "/o-nas/kariera", "/attachments/kariera", "/promo/", "/test/")
SECTION_NAMES = [
    "osobni", "podnikatele", "firmy", "hypoteky", "pujcky", "uvery", "kreditni-karty",
    "debetni-karty", "investice", "sporeni", "pojisteni", "bezpecnost", "premium", "ceniky",
    "sazebniky", "dokumenty", "podminky", "faq", "api", "kurzy", "bankovnictvi",
    "mobilni-aplikace", "general",
]
SECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("kreditni-karty", ("kreditni-kart", "kreditní kart", "kreditka", "easy karta", "style karta", "mastercard", "visa", "charge card")),
    ("debetni-karty", ("debetni-kart", "debetní kart", "platebni-kart", "platební kart")),
    ("hypoteky", ("hypotek", "hypoték")), ("pujcky", ("pujck", "půjčk")),
    ("uvery", ("uver", "úvěr")), ("investice", ("invest", "fond")),
    ("sporeni", ("sporen", "spořen", "vklad")), ("pojisteni", ("pojist", "pojišt")),
    ("bezpecnost", ("bezpec", "bezpeč", "phishing")), ("premium", ("premium", "exkluziv")),
    ("ceniky", ("cenik", "ceník")), ("sazebniky", ("sazebnik", "sazebník")),
    ("dokumenty", ("dokument", "download", "ke-stazeni", "ke-stažení")),
    ("podminky", ("podmink", "podmínk", "vop")), ("faq", ("faq", "caste-dotazy", "časté dotazy")),
    ("api", ("api", "developer")), ("kurzy", ("kurz", "exchange")),
    ("bankovnictvi", ("bankovnictv", "internetove-bankovnictvi", "internetové-bankovnictví")),
    ("mobilni-aplikace", ("mobilni-aplikace", "mobilní aplikace", "aplikace")),
    ("podnikatele", ("podnikatel",)), ("firmy", ("firmy", "korpor")), ("osobni", ("osobni", "osobní")),
]
CREDIT_CARD_QUERIES = ["kreditni karta", "kreditní karta", "kreditni karty", "kreditní karty", "kreditka", "easy karta", "style karta", "mastercard", "visa", "charge card", "debetni karta", "debetní karta"]
EXPLICIT_CREDIT_CARD_URLS = [
    f"{BASE_URL}/osobni/karty", f"{BASE_URL}/osobni/karty/kreditni-karty", f"{BASE_URL}/osobni/karty/debetni-karty",
    f"{BASE_URL}/osobni/karty/platebni-karty", f"{BASE_URL}/osobni/ucty/sluzby-k-uctum/platebni-karty",
]


@dataclass
class CrawlItem:
    url: str
    depth: int = 0
    source: str = "sitemap"
    priority: str | None = None
    lastmod: str | None = None


@dataclass
class Stats:
    sitemap_urls: int = 0
    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    docs_downloaded: int = 0
    docs_skipped: int = 0
    discovered_links: int = 0
    retry_events: int = 0
    outputs: list[str] = field(default_factory=list)


def ensure_dirs() -> None:
    for path in [DISCOVERY_DIR, RAW_HTML_DIR, STRUCTURED_DIR, DOCUMENTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    for sub in ["pricing", "mortgages", "cards", "terms", "loans", "insurance", "investments", "security", "general"]:
        (DOCUMENTS_DIR / sub).mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def normalize_url(url: str, base: str = BASE_URL) -> str:
    joined = urljoin(base, url)
    joined, _fragment = urldefrag(joined)
    p = urlparse(joined)
    path = re.sub(r"/{2,}", "/", p.path) or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((p.scheme or "https", p.netloc.lower(), path, "", p.query, ""))


def safe_slug(url: str, max_len: int = 120) -> str:
    p = urlparse(url)
    raw = f"{p.netloc}{p.path}".strip("/").replace("/", "_") or "index"
    slug = re.sub(r"[^\w.-]+", "_", raw)[:max_len]
    return f"{slug}_{sha256_text(url)[:10]}"


def is_internal(url: str) -> bool:
    return urlparse(url).netloc.lower() in {"rb.cz", "www.rb.cz"}


def should_skip_url(url: str) -> bool:
    path = urlparse(url).path
    return any(path.startswith(prefix) for prefix in SKIP_PREFIXES)


def is_document_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(DOCUMENT_EXTENSIONS)


def is_html_url(url: str) -> bool:
    return is_internal(url) and not should_skip_url(url) and not is_document_url(url)


def classify_section(url: str, title: str = "", text: str = "") -> str:
    hay = f"{url} {title} {text[:2000]}".lower()
    hay = hay.replace("%C3%AD".lower(), "i")
    for section, needles in SECTION_RULES:
        if any(n in hay for n in needles):
            return section
    return "general"


def document_subdir(section: str, url: str = "") -> str:
    hay = f"{section} {url}".lower()
    if any(k in hay for k in ["cenik", "sazebnik", "pricing"]):
        return "pricing"
    if "hypotek" in hay:
        return "mortgages"
    if any(k in hay for k in ["kart", "mastercard", "visa"]):
        return "cards"
    if any(k in hay for k in ["podmink", "terms", "vop"]):
        return "terms"
    if any(k in hay for k in ["pujck", "uver"]):
        return "loans"
    if "pojist" in hay:
        return "insurance"
    if "invest" in hay:
        return "investments"
    if "bezpec" in hay:
        return "security"
    return "general"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.5"})
    return s


def random_delay() -> None:
    time.sleep(random.uniform(0.5, 2.0))


def load_robots() -> RobotFileParser:
    rp = RobotFileParser()
    try:
        resp = requests.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        rp.parse(resp.text.splitlines())
    except Exception as exc:
        logger.warning(f"Robots.txt nelze načíst: {exc}")
    return rp


def allowed(rp: RobotFileParser, url: str) -> bool:
    try:
        if not rp:
            return True
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_manifest() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH, {"urls": {}, "documents": {}, "failed": {}})
    manifest.setdefault("urls", {})
    manifest.setdefault("documents", {})
    manifest.setdefault("failed", {})
    return manifest


def save_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    write_json(MANIFEST_PATH, manifest)


def fetch_with_retries(s: requests.Session, url: str, *, stream: bool = False, max_attempts: int = 3) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            random_delay()
            resp = s.get(url, timeout=REQUEST_TIMEOUT, stream=stream, allow_redirects=True)
            if resp.status_code < 500:
                return resp
            last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
        except Exception as exc:
            last_exc = exc
        if attempt < max_attempts:
            time.sleep((2 ** (attempt - 1)) + random.random())
    raise RuntimeError(f"Request failed after {max_attempts} attempts: {url}: {last_exc}")


def parse_sitemap_xml(xml: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    soup = BeautifulSoup(xml, "xml")
    sitemap_urls = [loc.get_text(strip=True) for loc in soup.select("sitemap > loc")]
    page_records: list[dict[str, Any]] = []
    for url_tag in soup.select("url"):
        loc = url_tag.find("loc")
        if not loc:
            continue
        page_records.append({
            "url": normalize_url(loc.get_text(strip=True)),
            "lastmod": (url_tag.find("lastmod") or soup.new_tag("x")).get_text(strip=True) or None,
            "priority": (url_tag.find("priority") or soup.new_tag("x")).get_text(strip=True) or None,
            "section": classify_section(loc.get_text(strip=True)),
        })
    return sitemap_urls, page_records


def discover_sitemaps() -> list[dict[str, Any]]:
    ensure_dirs()
    s = session()
    seen_sitemaps: set[str] = set()
    queue = deque([SITEMAP_URL])
    pages: dict[str, dict[str, Any]] = {}
    sitemap_sources: list[str] = []
    while queue:
        sitemap_url = normalize_url(queue.popleft())
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            resp = fetch_with_retries(s, sitemap_url)
            resp.raise_for_status()
            nested, records = parse_sitemap_xml(resp.content)
            sitemap_sources.append(sitemap_url)
            for nested_url in nested:
                if nested_url not in seen_sitemaps:
                    queue.append(nested_url)
            for record in records:
                if is_internal(record["url"]) and not should_skip_url(record["url"]):
                    pages[record["url"]] = record
        except Exception as exc:
            logger.warning(f"Sitemap chyba {sitemap_url}: {exc}")
    result = sorted(pages.values(), key=lambda r: r["url"])
    write_json(SITEMAPS_PATH, {"generated_at": now_iso(), "sitemap_sources": sitemap_sources, "total_urls": len(result), "urls": result})
    return result


def load_sitemap_records() -> list[dict[str, Any]]:
    if not SITEMAPS_PATH.exists():
        return discover_sitemaps()
    data = read_json(SITEMAPS_PATH, {})
    return data.get("urls", []) if isinstance(data, dict) else []


def extract_links_and_documents(html: str, base_url: str) -> tuple[set[str], set[str]]:
    soup = BeautifulSoup(html, "lxml")
    links: set[str] = set()
    docs: set[str] = set()
    for tag in soup.find_all(["a", "link"]):
        href = tag.get("href")
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = normalize_url(href, base_url)
        if not is_internal(url) or should_skip_url(url):
            continue
        if is_document_url(url):
            docs.add(url)
        elif is_html_url(url):
            links.add(url)
    return links, docs


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def table_to_struct(table: Tag, order: int) -> dict[str, Any] | None:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return {"order": order, "headers": rows[0], "rows": rows[1:]}


def html_to_structured(html: str, url: str, depth: int) -> tuple[dict[str, Any], str]:
    soup = BeautifulSoup(html, "lxml")
    for sel in ["script", "style", "noscript", "svg", "nav", "header", "footer", "app-navigation", "app-header", "app-footer", ".cookie-wall", ".cookie-banner"]:
        for tag in soup.select(sel):
            tag.decompose()
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical_url = normalize_url(canonical.get("href"), url) if canonical and canonical.get("href") else url
    title = clean_text((soup.find("h1") or soup.find("title") or soup.new_tag("span")).get_text(" ", strip=True)) or canonical_url
    main = soup.select_one("main, [role='main'], article, .page-wrapper, .content, app-root") or soup.body or soup
    text = clean_text(main.get_text("\n", strip=True))
    sections = []
    current = {"heading": title, "level": 1, "content": [], "order": 0}
    order = 0
    for el in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]):
        t = clean_text(el.get_text(" ", strip=True))
        if not t:
            continue
        if re.match(r"^h[1-6]$", el.name or ""):
            if current["content"]:
                sections.append({**current, "content": clean_text("\n".join(current["content"]))})
            order += 1
            current = {"heading": t, "level": int(el.name[1]), "content": [], "order": order}
        else:
            current["content"].append(t)
    if current["content"] or not sections:
        sections.append({**current, "content": clean_text("\n".join(current["content"]))})
    tables = [parsed for i, table in enumerate(main.find_all("table")) if (parsed := table_to_struct(table, i))]
    faq = []
    for i, detail in enumerate(main.find_all("details")):
        summary = detail.find("summary")
        q = clean_text(summary.get_text(" ", strip=True)) if summary else ""
        if summary:
            summary.extract()
        a = clean_text(detail.get_text(" ", strip=True))
        if q and a:
            faq.append({"question": q, "answer": a, "order": i})
    section = classify_section(canonical_url, title, text)
    structured = {
        "url": canonical_url, "title": title, "section": section, "depth": depth,
        "sections": sections, "tables": tables, "faq": faq,
        "metadata": {"source_type": "html", "crawled_at": now_iso(), "content_hash": sha256_text(text), "text_length": len(text)},
    }
    md_lines = [f"# {title}", "", f"Source: {canonical_url}", f"Section: {section}", ""]
    for sec in sections:
        md_lines.extend([f"{'#' * min(max(sec.get('level', 2), 2), 6)} {sec['heading']}", sec.get("content", ""), ""])
    for table in tables:
        md_lines.append("## Table")
        headers = table["headers"]
        md_lines.append(" | ".join(headers))
        md_lines.append(" | ".join(["---"] * len(headers)))
        for row in table["rows"]:
            md_lines.append(" | ".join(row))
        md_lines.append("")
    return structured, "\n".join(md_lines).strip() + "\n"


async def render_page(url: str) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="cs-CZ")
        await context.add_cookies([{"name": "cookieConsent", "value": "true", "domain": ".rb.cz", "path": "/"}])
        page = await context.new_page()
        page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
        await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
        for selector in ["button:has-text('Přijmout')", "button:has-text('Souhlasím')", "#onetrust-accept-btn-handler", ".js-cookie-accept"]:
            try:
                await page.locator(selector).first.click(timeout=1500)
                break
            except Exception:
                pass
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        for _ in range(5):
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(600)
        expand_selectors = [
            "details:not([open]) > summary", "button[aria-expanded='false']", "[role='tab']",
            "button:has-text('Zobrazit více')", "button:has-text('Více')", "button:has-text('Show more')",
            "mat-expansion-panel-header",
        ]
        for selector in expand_selectors:
            try:
                count = await page.locator(selector).count()
                for i in range(min(count, 80)):
                    try:
                        await page.locator(selector).nth(i).click(timeout=1000)
                        await page.wait_for_timeout(150)
                    except Exception:
                        continue
            except Exception:
                continue
        html = await page.content()
        await browser.close()
        return html


async def fetch_html(url: str, rp: RobotFileParser) -> str:
    if not allowed(rp, url):
        raise PermissionError(f"robots.txt disallow: {url}")
    try:
        return await render_page(url)
    except Exception as exc:
        logger.warning(f"Playwright fallback to requests for {url}: {exc}")
        s = session()
        resp = fetch_with_retries(s, url)
        resp.raise_for_status()
        return resp.text


def download_document(doc_url: str, page_url: str, manifest: dict[str, Any], rp: RobotFileParser, dry_run: bool = False) -> dict[str, Any]:
    doc_url = normalize_url(doc_url, page_url)
    if not allowed(rp, doc_url):
        raise PermissionError(f"robots.txt disallow document: {doc_url}")
    if doc_url in manifest["documents"] and manifest["documents"][doc_url].get("status") == "ok":
        return {"status": "skipped", "reason": "url_duplicate", **manifest["documents"][doc_url]}
    section = classify_section(doc_url)
    subdir = DOCUMENTS_DIR / document_subdir(section, doc_url)
    subdir.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(doc_url).path).suffix.lower() or ".bin"
    filename = safe_slug(doc_url) + ext
    out_path = subdir / filename
    if dry_run:
        return {"status": "dry_run", "url": doc_url, "path": str(out_path), "section": section}
    s = session()
    resp = fetch_with_retries(s, doc_url, stream=True)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}")
    expected = int(resp.headers.get("content-length") or 0)
    if expected > MAX_DOCUMENT_BYTES:
        raise RuntimeError(f"document too large: {expected}")
    h = hashlib.sha256()
    size = 0
    with out_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_DOCUMENT_BYTES:
                f.close()
                out_path.unlink(missing_ok=True)
                raise RuntimeError("document exceeded 100MB")
            h.update(chunk)
            f.write(chunk)
    checksum = h.hexdigest()
    for existing_url, rec in manifest["documents"].items():
        if existing_url != doc_url and rec.get("sha256") == checksum:
            out_path.unlink(missing_ok=True)
            meta = {"status": "skipped", "reason": "hash_duplicate", "duplicate_of": existing_url, "url": doc_url, "sha256": checksum}
            manifest["documents"][doc_url] = meta
            return meta
    meta = {"status": "ok", "url": doc_url, "source_page": page_url, "path": str(out_path), "filename": filename, "section": section, "category_dir": subdir.name, "extension": ext.lstrip("."), "size_bytes": size, "sha256": checksum, "downloaded_at": now_iso(), "content_type": resp.headers.get("content-type")}
    manifest["documents"][doc_url] = meta
    append_jsonl(DOC_METADATA_PATH, meta)
    return meta


async def process_url(item: CrawlItem, manifest: dict[str, Any], rp: RobotFileParser, docs_only: bool, dry_run: bool) -> tuple[str, list[str], list[str], dict[str, Any]]:
    html = await fetch_html(item.url, rp)
    content_hash = sha256_text(html)
    previous = manifest["urls"].get(item.url)
    if previous and previous.get("content_hash") == content_hash and previous.get("status") == "ok" and not docs_only:
        return "skipped", [], [], {"reason": "unchanged", "content_hash": content_hash}
    links, docs = extract_links_and_documents(html, item.url)
    if docs_only:
        return "ok", sorted(links), sorted(docs), {"content_hash": content_hash}
    structured, markdown = html_to_structured(html, item.url, item.depth)
    slug = safe_slug(item.url)
    html_path = RAW_HTML_DIR / f"{slug}.html"
    json_path = STRUCTURED_DIR / f"{slug}.json"
    md_path = STRUCTURED_DIR / f"{slug}.md"
    if not dry_run:
        html_path.write_text(html, encoding="utf-8")
        write_json(json_path, structured)
        md_path.write_text(markdown, encoding="utf-8")
    meta = {"url": item.url, "status": "ok", "depth": item.depth, "source": item.source, "section": structured["section"], "title": structured["title"], "content_hash": content_hash, "text_hash": structured["metadata"]["content_hash"], "crawled_at": now_iso(), "raw_html_path": str(html_path), "json_path": str(json_path), "markdown_path": str(md_path), "document_links": len(docs), "internal_links": len(links), "lastmod": item.lastmod, "priority": item.priority}
    manifest["urls"][item.url] = meta
    append_jsonl(CRAWL_LOG_PATH, meta)
    return "ok", sorted(links), sorted(docs), meta


def build_initial_queue(records: list[dict[str, Any]], section: str | None, docs_only: bool) -> deque[CrawlItem]:
    queue: deque[CrawlItem] = deque()
    for rec in records:
        url = normalize_url(rec["url"])
        sec = rec.get("section") or classify_section(url)
        if section and sec != section:
            continue
        if is_html_url(url) or (docs_only and is_document_url(url)):
            queue.append(CrawlItem(url=url, depth=0, source="sitemap", priority=rec.get("priority"), lastmod=rec.get("lastmod")))
    for url in EXPLICIT_CREDIT_CARD_URLS:
        if not section or section in {"kreditni-karty", "debetni-karty"}:
            queue.append(CrawlItem(url=normalize_url(url), depth=0, source="credit-card-explicit"))
    for rec in records:
        hay = rec["url"].lower()
        if any(q.replace(" ", "-") in hay or q in hay for q in CREDIT_CARD_QUERIES):
            queue.append(CrawlItem(url=normalize_url(rec["url"]), depth=0, source="credit-card-sitemap", priority=rec.get("priority"), lastmod=rec.get("lastmod")))
    return queue


async def run_crawl(sitemap_only: bool, section: str | None, max_pages: int | None, dry_run: bool, resume: bool, docs_only: bool) -> Stats:
    ensure_dirs()
    records = discover_sitemaps() if not SITEMAPS_PATH.exists() or sitemap_only else load_sitemap_records()
    stats = Stats(sitemap_urls=len(records))
    if sitemap_only:
        return stats
    if section and section not in SECTION_NAMES:
        raise typer.BadParameter(f"Neznámá sekce {section}. Povolené: {', '.join(SECTION_NAMES)}")
    rp = load_robots()
    manifest = load_manifest()
    queue = build_initial_queue(records, section, docs_only)
    seen = set()
    processed_this_run = 0
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn(), console=console) as progress:
        task = progress.add_task("Crawling rb.cz", total=max_pages or len(queue) or None)
        while queue:
            item = queue.popleft()
            item.url = normalize_url(item.url)
            if item.url in seen or should_skip_url(item.url):
                continue
            seen.add(item.url)
            if max_pages is not None and processed_this_run >= max_pages:
                break
            if resume and manifest["urls"].get(item.url, {}).get("status") == "ok" and not docs_only:
                stats.skipped += 1
                continue
            attempts = manifest["failed"].get(item.url, {}).get("attempts", 0)
            try:
                status, links, docs, meta = await process_url(item, manifest, rp, docs_only, dry_run)
                if status == "skipped":
                    stats.skipped += 1
                else:
                    stats.crawled += 1
                processed_this_run += 1
                stats.discovered_links += len(links)
                for doc_url in docs:
                    try:
                        dmeta = download_document(doc_url, item.url, manifest, rp, dry_run=dry_run)
                        if dmeta.get("status") == "ok":
                            stats.docs_downloaded += 1
                        else:
                            stats.docs_skipped += 1
                    except Exception as exc:
                        stats.failed += 1
                        append_jsonl(CRAWL_LOG_PATH, {"url": doc_url, "source_page": item.url, "status": "document_failed", "error": str(exc), "timestamp": now_iso()})
                if item.depth < MAX_DEPTH and not docs_only:
                    for link in links:
                        if link not in seen and is_html_url(link):
                            if section and classify_section(link) != section:
                                continue
                            queue.append(CrawlItem(url=link, depth=item.depth + 1, source=item.url))
                manifest["failed"].pop(item.url, None)
            except Exception as exc:
                attempts += 1
                stats.failed += 1
                manifest["failed"][item.url] = {"attempts": attempts, "last_error": str(exc), "last_attempt_at": now_iso()}
                append_jsonl(CRAWL_LOG_PATH, {"url": item.url, "status": "failed", "attempts": attempts, "error": str(exc), "timestamp": now_iso()})
                if attempts < 3:
                    stats.retry_events += 1
                    time.sleep((2 ** (attempts - 1)) + random.random())
                    queue.append(item)
            finally:
                save_manifest(manifest)
                progress.advance(task)
    return stats


@app.callback(invoke_without_command=True)
def main(
    sitemap_only: bool = typer.Option(False, "--sitemap-only", help="Jen sitemap discovery."),
    section: str | None = typer.Option(None, "--section", help="Crawlovat jen jednu klasifikovanou sekci."),
    max_pages: int | None = typer.Option(None, "--max-pages", min=1, help="Limit počtu HTML stránek pro test run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Jen vypíše/ověří bez ukládání obsahu a dokumentů."),
    resume: bool = typer.Option(False, "--resume", help="Pokračovat podle manifestu."),
    docs_only: bool = typer.Option(False, "--docs-only", help="Jen objevovat/stahovat dokumenty z HTML stránek."),
) -> None:
    stats = asyncio.run(run_crawl(sitemap_only, section, max_pages, dry_run, resume, docs_only))
    table = Table(title="Enterprise rb.cz crawl summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in stats.__dict__.items():
        if key != "outputs":
            table.add_row(key, str(value))
    console.print(table)


if __name__ == "__main__":
    app()

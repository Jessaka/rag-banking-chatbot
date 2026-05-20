#!/usr/bin/env python3
"""
Downloader PDF sazebníků, ceníků, obchodních podmínek a produktových
dokumentů z rb.cz.

Strategie:
  1. Načte sitemap.xml z rb.cz.
  2. Vybere relevantní stránky podle kategorie (--category).
  3. Z HTML stránek extrahuje PDF odkazy z <a>, data atributů a inline HTML.
  4. Stáhne PDF do data/documents/.
  5. Zapíše metadata do data/documents/metadata.jsonl.
  6. Deduplikuje podle normalizované URL a podle SHA-256 hashe obsahu.

Použití:
  python scripts/download_documents.py --category pricing
  python scripts/download_documents.py --category mortgages
  python scripts/download_documents.py --category cards
  python scripts/download_documents.py --category pricing --dry-run
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
import typer
from bs4 import BeautifulSoup
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
DOCUMENTS_DIR = config.DATA_DIR / "documents"
METADATA_PATH = DOCUMENTS_DIR / "metadata.jsonl"

USER_AGENT = (
    "Mozilla/5.0 (compatible; RAG-Banking-Document-Downloader/1.0; "
    "educational project)"
)

REQUEST_TIMEOUT = 25
MAX_PDF_SIZE_BYTES = 80 * 1024 * 1024

DOCUMENT_KEYWORDS = [
    "pdf", "sazebnik", "sazební", "cenik", "ceník", "poplatek", "poplatky",
    "obchodni-podminky", "obchodní podmínky", "podminky", "podmínky",
    "vop", "dokumenty-ke-stazeni", "dokumenty-ke-stažení", "dokumenty",
    "predsmluvni", "předsmluvní", "informacni-list", "informační list",
    "produktovy-list", "produktový list", "urokove-sazby", "úrokové sazby",
]

CATEGORY_PATTERNS: dict[str, list[str]] = {
    "pricing": [
        "cenik", "ceník", "sazebnik", "sazební", "poplatek", "poplatky",
        "price", "pricing", "tariff", "fee", "urokove-sazby", "úrokové sazby",
        "podpora/cenik", "sazebniky",
    ],
    "mortgages": [
        "hypoteka", "hypote", "hypo", "mortgage", "uver-na-bydleni",
        "úvěr na bydlení", "refinancovani-hypoteky", "americka-hypoteka",
    ],
    "cards": [
        "karta", "karty", "card", "kreditni", "kreditní", "debetni", "debetní",
        "platebni-karty", "platební karty", "kk-", "/karty/",
    ],
}

SKIP_PATH_PREFIXES = (
    "/en/", "/uk/", "/o-nas/kariera", "/attachments/kariera", "/promo/",
    "/test/", "/meetit", "/affiliat",
)


@dataclass
class DocumentCandidate:
    url: str
    title: str
    source_page: str
    category: str


@dataclass
class DownloadResult:
    discovered: int = 0
    downloaded: int = 0
    skipped_url: int = 0
    skipped_hash: int = 0
    failed: int = 0
    crawled_pages: int = 0
    metadata_rows: list[dict] = field(default_factory=list)


class RBDocumentDownloader:
    def __init__(
        self,
        category: str,
        output_dir: Path = DOCUMENTS_DIR,
        max_pages: int = 500,
        delay_min: float = 0.5,
        delay_max: float = 1.5,
        dry_run: bool = False,
    ) -> None:
        if category not in CATEGORY_PATTERNS:
            valid = ", ".join(CATEGORY_PATTERNS)
            raise typer.BadParameter(f"Neznámá kategorie '{category}'. Povolené: {valid}")

        self.category = category
        self.output_dir = output_dir
        self.metadata_path = output_dir / "metadata.jsonl"
        self.max_pages = max_pages
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.dry_run = dry_run

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.5",
        })

        self.robots = self._load_robots()
        self.known_urls, self.known_hashes = self._load_existing_metadata()
        self.result = DownloadResult()

    # ── URL a filtrování ─────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url: str, base: str = BASE_URL) -> str:
        full = urljoin(base, url)
        parsed = urlparse(full)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc.lower()
        path = re.sub(r"/{2,}", "/", parsed.path)
        if ".pdf" in path.lower():
            return urlunparse((scheme, netloc, path, "", parsed.query, ""))
        return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", "", ""))

    @staticmethod
    def _is_rb_url(url: str) -> bool:
        return urlparse(url).netloc.lower() in {"www.rb.cz", "rb.cz"}

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        return ".pdf" in urlparse(url).path.lower()

    @staticmethod
    def _text_slug(text: str, max_len: int = 90) -> str:
        text = unquote(text).lower()
        text = re.sub(r"\.pdf$", "", text)
        text = re.sub(r"[^a-z0-9áčďéěíňóřšťúůýž_-]+", "-", text, flags=re.IGNORECASE)
        text = re.sub(r"-+", "-", text).strip("-_")
        return (text[:max_len].strip("-_") or "document")

    def _matches_category(self, text: str) -> bool:
        normalized = unquote(text).lower()
        category_patterns = CATEGORY_PATTERNS[self.category]
        if any(pattern in normalized for pattern in category_patterns):
            return True
        # Pricing má být záměrně širší: sazebníky/ceníky/podmínky bývají sdílené
        # napříč produkty a často neleží přímo v produktové URL.
        if self.category == "pricing" and any(pattern in normalized for pattern in DOCUMENT_KEYWORDS):
            return True
        return False

    def _looks_like_document(self, text: str) -> bool:
        normalized = unquote(text).lower()
        return any(pattern in normalized for pattern in DOCUMENT_KEYWORDS)

    def _is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if any(parsed.path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
            return False
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _load_robots(self) -> RobotFileParser:
        rp = RobotFileParser()
        rp.set_url(ROBOTS_URL)
        try:
            resp = self.session.get(ROBOTS_URL, timeout=10)
            resp.raise_for_status()
            rp.parse(resp.text.splitlines())
            logger.info("robots.txt načten")
        except Exception as exc:
            logger.warning(f"Nelze načíst robots.txt: {exc} – pokračuji opatrně")
        return rp

    def _fetch(self, url: str, stream: bool = False) -> requests.Response | None:
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, stream=stream, allow_redirects=True)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning(f"HTTP chyba: {url} – {exc}")
            return None

    def _polite_delay(self) -> None:
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    # ── Metadata / deduplikace ───────────────────────────────────────────────

    def _load_existing_metadata(self) -> tuple[set[str], set[str]]:
        known_urls: set[str] = set()
        known_hashes: set[str] = set()
        if not self.metadata_path.exists():
            return known_urls, known_hashes

        for line in self.metadata_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("url"):
                known_urls.add(self._normalize_url(row["url"]))
            if row.get("sha256"):
                known_hashes.add(row["sha256"])
        return known_urls, known_hashes

    def _append_metadata(self, row: dict) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with self.metadata_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    # ── Discovery ────────────────────────────────────────────────────────────

    def _load_sitemap_urls(self) -> list[str]:
        resp = self._fetch(SITEMAP_URL)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.content, "xml")
        seen: set[str] = set()
        urls: list[str] = []
        for loc in soup.find_all("loc"):
            normalized = self._normalize_url(loc.get_text(strip=True))
            if normalized in seen or not self._is_rb_url(normalized):
                continue
            path = urlparse(normalized).path
            if any(path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
                continue
            seen.add(normalized)
            urls.append(normalized)
        logger.info(f"Sitemap: {len(urls)} unikátních rb.cz URL")
        return urls

    def _candidate_pages(self, urls: list[str]) -> list[str]:
        candidates = [u for u in urls if self._matches_category(u) or self._looks_like_document(u)]

        # Přidáme známé dokumentové landing pages, i pokud by nebyly v sitemap.
        seed_pages = [
            f"{BASE_URL}/podpora/cenik",
            f"{BASE_URL}/informacni-servis/dokumenty-ke-stazeni",
            f"{BASE_URL}/informacni-servis/predsmluvni-dokumenty",
            f"{BASE_URL}/informacni-servis/urokove-sazby",
        ]
        if self.category == "mortgages":
            seed_pages.extend([
                f"{BASE_URL}/osobni/hypoteky",
                f"{BASE_URL}/osobni/hypoteky/hypoteka-na-bydleni",
            ])
        elif self.category == "cards":
            seed_pages.extend([
                f"{BASE_URL}/osobni/karty",
                f"{BASE_URL}/osobni/karty/kreditni-karty",
                f"{BASE_URL}/osobni/karty/platebni-karty",
            ])

        seen: set[str] = set()
        ordered = []
        for u in seed_pages + candidates:
            normalized = self._normalize_url(u)
            if normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
        return ordered[: self.max_pages]

    def _extract_pdf_links(self, html: bytes, page_url: str) -> list[DocumentCandidate]:
        soup = BeautifulSoup(html, "lxml")
        candidates: dict[str, DocumentCandidate] = {}
        raw_html = html.decode("utf-8", errors="replace")

        def add_candidate(raw_url: str, title: str) -> None:
            if not raw_url or not self._is_pdf_url(raw_url):
                return
            normalized = self._normalize_url(raw_url, page_url)
            if not self._is_rb_url(normalized):
                return
            combined = f"{normalized} {title} {page_url}"
            if not (self._matches_category(combined) or self._looks_like_document(combined)):
                return
            title_clean = re.sub(r"\s+", " ", title).strip()
            if not title_clean:
                title_clean = Path(urlparse(normalized).path).stem.replace("-", " ")
            candidates.setdefault(
                normalized,
                DocumentCandidate(
                    url=normalized,
                    title=title_clean,
                    source_page=page_url,
                    category=self.category,
                ),
            )

        for tag in soup.find_all("a", href=True):
            add_candidate(tag.get("href", ""), tag.get_text(" ", strip=True))

        for attr in ("data-href", "data-url", "data-src", "data-file", "href"):
            for tag in soup.find_all(attrs={attr: True}):
                add_candidate(str(tag.get(attr, "")), tag.get_text(" ", strip=True))

        regex_pdfs = re.findall(
            r"[\"']([^\"'<>\s]+\.pdf(?:\?[^\"'<>\s]*)?)[\"']",
            raw_html,
            flags=re.IGNORECASE,
        )
        for raw_url in regex_pdfs:
            add_candidate(raw_url, "")

        return list(candidates.values())

    def discover(self) -> list[DocumentCandidate]:
        sitemap_urls = self._load_sitemap_urls()
        pages = self._candidate_pages(sitemap_urls)
        logger.info(f"Kategorie '{self.category}': {len(pages)} stránek k prohledání")

        discovered: dict[str, DocumentCandidate] = {}
        direct_pdfs = [u for u in sitemap_urls if self._is_pdf_url(u) and self._matches_category(u)]
        for pdf_url in direct_pdfs:
            discovered[pdf_url] = DocumentCandidate(
                url=pdf_url,
                title=Path(urlparse(pdf_url).path).stem.replace("-", " "),
                source_page=SITEMAP_URL,
                category=self.category,
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Prohledávám rb.cz…", total=len(pages))
            for page_url in pages:
                progress.update(task, advance=1, description=f"[dim]{urlparse(page_url).path[:60]}[/dim]")
                if not self._is_allowed(page_url):
                    continue
                self._polite_delay()
                resp = self._fetch(page_url)
                if resp is None:
                    continue
                content_type = resp.headers.get("Content-Type", "")
                if "html" not in content_type and "xml" not in content_type:
                    continue
                self.result.crawled_pages += 1
                for candidate in self._extract_pdf_links(resp.content, page_url):
                    discovered.setdefault(candidate.url, candidate)

        self.result.discovered = len(discovered)
        return sorted(discovered.values(), key=lambda item: item.url)

    # ── Download ─────────────────────────────────────────────────────────────

    def _filename_for(self, candidate: DocumentCandidate, content_hash: str) -> str:
        original = Path(urlparse(candidate.url).path).name
        if original.lower().endswith(".pdf"):
            stem = self._text_slug(Path(original).stem)
        else:
            stem = self._text_slug(candidate.title)
        return f"{self.category}_{stem}_{content_hash[:10]}.pdf"

    def _download_candidate(self, candidate: DocumentCandidate) -> None:
        normalized_url = self._normalize_url(candidate.url)
        if normalized_url in self.known_urls:
            self.result.skipped_url += 1
            return

        if self.dry_run:
            logger.info(f"[dry-run] {candidate.title}: {candidate.url}")
            return

        if not self._is_allowed(candidate.url):
            self.result.failed += 1
            return

        self._polite_delay()
        resp = self._fetch(candidate.url, stream=True)
        if resp is None:
            self.result.failed += 1
            return

        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not self._is_pdf_url(resp.url):
            logger.warning(f"Přeskakuji ne-PDF response: {candidate.url} ({content_type})")
            self.result.failed += 1
            return

        total_size = int(resp.headers.get("Content-Length") or 0)
        if total_size > MAX_PDF_SIZE_BYTES:
            logger.warning(f"Přeskakuji příliš velké PDF ({total_size:,} B): {candidate.url}")
            self.result.failed += 1
            return

        content = resp.content
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash in self.known_hashes:
            self.result.skipped_hash += 1
            self.known_urls.add(normalized_url)
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = self._filename_for(candidate, content_hash)
        dest = self.output_dir / filename
        dest.write_bytes(content)

        metadata = {
            "url": normalized_url,
            "final_url": self._normalize_url(resp.url),
            "title": candidate.title,
            "category": candidate.category,
            "source_page": candidate.source_page,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "filename": filename,
            "path": str(dest),
            "sha256": content_hash,
            "size_bytes": len(content),
            "content_type": content_type,
        }
        self._append_metadata(metadata)
        self.result.metadata_rows.append(metadata)
        self.known_urls.add(normalized_url)
        self.known_hashes.add(content_hash)
        self.result.downloaded += 1
        logger.info(f"Staženo: [green]{filename}[/green] ({len(content):,} B)")

    def download(self, candidates: list[DocumentCandidate]) -> DownloadResult:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Stahuji PDF…", total=len(candidates))
            for candidate in candidates:
                progress.update(task, advance=1, description=f"[dim]{candidate.title[:55]}[/dim]")
                self._download_candidate(candidate)
        return self.result

    def run(self) -> DownloadResult:
        console.print(Panel.fit(
            "[bold cyan]Raiffeisenbank Document Downloader[/bold cyan]\n"
            f"[dim]Kategorie: {self.category} | Výstup: {self.output_dir} | Dry-run: {self.dry_run}[/dim]",
            border_style="cyan",
        ))

        candidates = self.discover()
        console.print(f"\n[green]✓[/green] Nalezeno PDF kandidátů: [bold]{len(candidates)}[/bold]")
        self.download(candidates)
        self._print_summary()
        return self.result

    def _print_summary(self) -> None:
        table = Table(title="Výsledky downloadu dokumentů", border_style="green")
        table.add_column("Metrika", style="cyan")
        table.add_column("Hodnota", justify="right", style="bold")
        table.add_row("Procrawlované stránky", str(self.result.crawled_pages))
        table.add_row("Nalezené PDF URL", str(self.result.discovered))
        table.add_row("Staženo", str(self.result.downloaded))
        table.add_row("Přeskočeno podle URL", str(self.result.skipped_url))
        table.add_row("Přeskočeno podle hashe", str(self.result.skipped_hash))
        table.add_row("Chyby", str(self.result.failed))
        console.print(table)
        console.print(Panel.fit(
            f"Soubory: [cyan]{self.output_dir}[/cyan]\n"
            f"Metadata: [cyan]{self.metadata_path}[/cyan]",
            border_style="green",
        ))


@app.command()
def main(
    category: str = typer.Option(
        "pricing",
        "--category",
        "-c",
        help="Kategorie dokumentů: pricing, mortgages, cards.",
    ),
    output_dir: Path = typer.Option(
        DOCUMENTS_DIR,
        "--output-dir",
        "-o",
        help="Adresář pro stažené PDF a metadata.",
    ),
    max_pages: int = typer.Option(
        500,
        "--max-pages",
        "-m",
        help="Maximální počet stránek ze sitemap k prohledání.",
    ),
    delay_min: float = typer.Option(0.5, "--delay-min", help="Minimální delay mezi requesty v sekundách."),
    delay_max: float = typer.Option(1.5, "--delay-max", help="Maximální delay mezi requesty v sekundách."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Jen najde PDF, nestahuje soubory."),
) -> None:
    downloader = RBDocumentDownloader(
        category=category,
        output_dir=output_dir,
        max_pages=max_pages,
        delay_min=delay_min,
        delay_max=delay_max,
        dry_run=dry_run,
    )
    downloader.run()


if __name__ == "__main__":
    app()

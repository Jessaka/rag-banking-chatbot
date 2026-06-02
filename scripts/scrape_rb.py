#!/usr/bin/env python3
"""
Web scraper pro rb.cz – hledání PDF dokumentů a FAQ stránek.

Strategie (etický crawl):
  1. Načte robots.txt a sestaví pravidla pro povolené cesty
  2. Stáhne sitemap.xml a extrahuje 2 300+ URL webu rb.cz
  3. Filtruje URL do prioritních kategorií (sazebníky, podmínky, FAQ…)
  4. Pro každou povolenou stránku extrahuje:
       – PDF linky  → stahnout do data/raw/
       – FAQ obsah  → uložit jako .txt do data/raw/
  5. Zapíše seznam všech nalezených PDF URL do data/sources.txt

Etická pravidla:
  – robots.txt compliance (urllib.robotparser)
  – 1–3 s náhodný delay mezi requesty
  – User-Agent identifikuje bota a odkazuje na projekt
  – Maximální počet stažených stránek (--max-pages) jako pojistka
  – Pouze česká jazyková mutace webu (přeskočí /en/, /uk/)

Použití:
  python scripts/scrape_rb.py                    # plné spuštění
  python scripts/scrape_rb.py --dry-run          # pouze nalezení URL, bez stahování
  python scripts/scrape_rb.py --max-pages 100    # omezení rozsahu
  python scripts/scrape_rb.py --no-faq           # přeskočí FAQ stránky
  python scripts/scrape_rb.py --delay 2.5        # vlastní delay v sekundách
"""

from __future__ import annotations

import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
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

# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

BASE_URL = "https://www.rb.cz"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
ROBOTS_URL = f"{BASE_URL}/robots.txt"

USER_AGENT = (
    "Mozilla/5.0 (compatible; RAG-Banking-Scraper/1.0; "
    "educational project; github.com/your-repo)"
)

# PDF cesty výslovně zakázané v robots.txt
ROBOTS_BLOCKED_PDFS: set[str] = {
    "/attachments/kariera/",
    "/attachments/pi/karty/vypoved-smlouvy-kk-klientem.pdf",
    "/attachments/pi/pravidla-reklamni-akce/pravidla-reklamni-akce-bezny-ucet-s-extra-bonusem.pdf",
    "/attachments/pi/pravidla-reklamni-akce/pravidla-reklamni-akce-bezny-ucet-s-extra-bonusem-2.pdf",
    "/attachments/pi/ucty/pravidla-reklamni-akce-vyhody-pro-klienty-ing.pdf",
}

# Klíčová slova pro výběr prioritních stránek ze sitemapy
PRIORITY_KEYWORDS: list[str] = [
    "cenik", "sazebni", "podminky", "dokumenty-ke-stazeni",
    "predsmluvni", "urokove-sazby", "vop", "ramcova-smlouva",
    "caste-dotazy", "faq", "podpora",
    "hypoteka", "bezny-ucet", "sporici-ucet", "stavebni-sporeni",
    "penzijni", "kreditni-kart", "debitni-kart",
    "pojisteni", "investice", "podilove-fondy", "certifikat",
    "kontokorent", "pujcka", "uver", "leasing",
    "platebni-styk", "internet-banking", "mobilni-banking",
    "produktovy-list", "informacni-list",
]

# Cesty ke kompletnímu přeskočení (nesouvisí s bankovními produkty)
SKIP_PATH_PREFIXES: tuple[str, ...] = (
    "/o-nas/", "/attachments/kariera",
    "/promo/", "/test/", "/ing",
    "/meetit", "/zalozeni-uctu",
    "/informacni-servis/aml",
    "/informacni-servis/aktuality/",
    "/kariera/",
    "/media/",
    "/investori/",
    "/en/", "/uk/",
    "/affiliat",
)

# Substrings v URL které způsobí přeskočení (stará/irelevantní data)
SKIP_URL_SUBSTRINGS: tuple[str, ...] = (
    "marketingove-akce", "pravidla-akce", "pravidla-souteze",
    "/2014", "/2015", "/2016", "/2017", "/2018", "/2019", "/2020",
    "2014-", "2015-", "2016-", "2017-", "2018-", "2019-", "2020-",
)

# CSS selektory pro hlavní obsah stránky (FAQ extrakce)
CONTENT_SELECTORS: list[str] = [
    "main", "article", '[role="main"]',
    ".page-content", ".content-area", ".wysiwyg",
    "#content", ".main-content",
]

# Tagy ignorované při extrakci FAQ textu
IGNORED_TAGS: tuple[str, ...] = (
    "script", "style", "nav", "header", "footer",
    "aside", "form", "noscript", "iframe", "svg",
    "button", "input", "select",
)


# ---------------------------------------------------------------------------
# Datové struktury
# ---------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    pdf_urls: list[str] = field(default_factory=list)
    faq_files: list[Path] = field(default_factory=list)
    pages_crawled: int = 0
    pages_skipped: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# RBScraper – hlavní třída
# ---------------------------------------------------------------------------

class RBScraper:
    """
    Etický scraper pro rb.cz.

    Workflow: sitemap → filtrování → crawl prioritních stránek
             → extrakce PDF + FAQ → stahování → sources.txt
    """

    def __init__(
        self,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
        max_pages: int = 600,
        download_pdfs: bool = True,
        save_faq: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_pages = max_pages
        self.download_pdfs = download_pdfs
        self.save_faq = save_faq
        self.dry_run = dry_run

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.5",
        })

        self.robots = self._load_robots()
        self.visited: set[str] = set()
        self.found_pdfs: set[str] = set()
        self.result = ScrapeResult()

    # ── Robots.txt ──────────────────────────────────────────────────────────

    def _load_robots(self) -> RobotFileParser:
        """Načte a naparsuje robots.txt z rb.cz."""
        rp = RobotFileParser()
        rp.set_url(ROBOTS_URL)
        try:
            resp = self.session.get(ROBOTS_URL, timeout=10)
            resp.raise_for_status()
            rp.parse(resp.text.splitlines())
            logger.info("robots.txt načten a naparsován")
        except Exception as exc:
            logger.warning(f"Nelze načíst robots.txt: {exc} – pokračuji opatrně")
        return rp

    def _is_allowed(self, url: str) -> bool:
        """
        Vrátí True pokud je URL povolena robots.txt a není
        v seznamu výslovně přeskočených cest.
        """
        parsed = urlparse(url)
        path = parsed.path

        # Přímé přeskočení vybraných cest
        if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
            return False

        # Přeskočení stránek se starým nebo irelevantním obsahem
        full_url_lower = url.lower()
        if any(s in full_url_lower for s in SKIP_URL_SUBSTRINGS):
            return False

        # Kontrola robots.txt
        if not self.rp_can_fetch(url):
            return False

        return True

    def rp_can_fetch(self, url: str) -> bool:
        """Obaluje RobotFileParser.can_fetch() s ochranou před chybou."""
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True  # V případě chyby parseru povolíme

    # ── HTTP vrstva ──────────────────────────────────────────────────────────

    def _fetch(self, url: str, stream: bool = False) -> requests.Response | None:
        """Stáhne URL s respektováním rate limitu a timeoutu."""
        try:
            resp = self.session.get(
                url,
                timeout=20,
                stream=stream,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.debug(f"404: {url}")
            else:
                logger.warning(f"HTTP chyba ({exc.response.status_code if exc.response else '?'}): {url}")
            self.result.errors += 1
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Chyba sítě: {url} – {exc}")
            self.result.errors += 1
            return None

    def _polite_delay(self) -> None:
        """Náhodný zdvořilostní delay mezi requesty."""
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    # ── URL utilitky ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url: str, base: str = BASE_URL) -> str:
        """Normalizuje URL: doplní doménu, odstraní fragment, query kde nechceme."""
        full = urljoin(base, url)
        p = urlparse(full)
        # Zachováme query string pro PDF (někdy obsahuje verzi souboru)
        if p.path.endswith(".pdf"):
            return urlunparse((p.scheme, p.netloc, p.path, "", p.query, ""))
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

    @staticmethod
    def _is_rb_url(url: str) -> bool:
        return urlparse(url).netloc in ("www.rb.cz", "rb.cz")

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        return ".pdf" in urlparse(url).path.lower()

    @staticmethod
    def _is_blocked_pdf(url: str) -> bool:
        path = urlparse(url).path
        return any(blocked in path for blocked in ROBOTS_BLOCKED_PDFS)

    # ── Sitemap ──────────────────────────────────────────────────────────────

    def _load_sitemap_urls(self) -> list[str]:
        """
        Stáhne sitemap.xml a vrátí seznam relevantních českých URL.

        Filtruje:
          – anglické a ukrajinské mutace (/en/, /uk/)
          – cesty bez vztahu k bankovním produktům
          – duplicity
        """
        resp = self._fetch(SITEMAP_URL)
        if resp is None:
            logger.error("Nelze načíst sitemap – aborting")
            return []

        soup = BeautifulSoup(resp.content, "xml")
        all_locs = [loc.text.strip() for loc in soup.find_all("loc")]

        # Deduplikace (sitemap obsahuje duplicity z hreflang)
        seen: set[str] = set()
        unique_urls: list[str] = []
        for u in all_locs:
            normalized = self._normalize_url(u)
            if normalized not in seen:
                seen.add(normalized)
                unique_urls.append(normalized)

        # Filtr – pouze česká verze webu
        cs_urls = [
            u for u in unique_urls
            if self._is_rb_url(u)
            and not any(u.replace(BASE_URL, "").startswith(p) for p in ("/en/", "/uk/", "/en", "/uk"))
        ]

        logger.info(f"Sitemap: {len(all_locs)} záznamů → {len(cs_urls)} českých URL")
        return cs_urls

    def _prioritize_urls(self, urls: list[str]) -> tuple[list[str], list[str]]:
        """
        Rozdělí URL na prioritní (s bankovními klíčovými slovy)
        a ostatní (crawlujeme jen pokud nenajdeme dost PDF).
        """
        priority, rest = [], []
        for u in urls:
            path = u.replace(BASE_URL, "").lower()
            if any(kw in path for kw in PRIORITY_KEYWORDS):
                priority.append(u)
            else:
                rest.append(u)
        return priority, rest

    # ── Extrakce PDF linků ────────────────────────────────────────────────────

    def _extract_pdf_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        """
        Extrahuje PDF linky ze stránky – hledá v:
          – <a href> odkazech
          – data atributech (data-href, data-url, data-src)
          – inline skript tazích (regex pro /attachments/*.pdf)
        """
        pdf_urls: set[str] = set()
        raw_html = str(soup)

        # 1. Standardní <a href> linky
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if self._is_pdf_url(href):
                normalized = self._normalize_url(href, page_url)
                if self._is_rb_url(normalized):
                    pdf_urls.add(normalized)

        # 2. Data atributy (někdy používané JS komponentami)
        for attr in ("data-href", "data-url", "data-src", "data-file"):
            for tag in soup.find_all(attrs={attr: True}):
                val = tag[attr]
                if self._is_pdf_url(val):
                    normalized = self._normalize_url(val, page_url)
                    if self._is_rb_url(normalized):
                        pdf_urls.add(normalized)

        # 3. Regex sken HTML pro /attachments/*.pdf (inline JSON, script data)
        regex_pdfs = re.findall(
            r'["\'](/attachments/[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?)["\']',
            raw_html,
        )
        for rel in regex_pdfs:
            normalized = self._normalize_url(rel, BASE_URL)
            pdf_urls.add(normalized)

        # Filtr – odstraníme zakázané PDF
        return [
            u for u in pdf_urls
            if not self._is_blocked_pdf(u)
        ]

    # ── Extrakce FAQ textu ────────────────────────────────────────────────────

    def _is_faq_page(self, soup: BeautifulSoup, url: str) -> bool:
        """Heuristika: je tato stránka FAQ / Časté dotazy?"""
        path = url.replace(BASE_URL, "").lower()
        if "faq" in path or "caste-dotazy" in path or "podpora" in path:
            return True
        # Strukturální detekce: stránka má mnoho <details> nebo accordion prvků
        details_count = len(soup.find_all("details"))
        return details_count >= 3

    def _extract_faq_text(self, soup: BeautifulSoup, url: str) -> str | None:
        """
        Extrahuje čistý text FAQ stránky.

        Pokud stránka obsahuje <details> (accordion), formátuje jako Q&A.
        Jinak extrahuje hlavní obsah bez navigace a footer.
        """
        # Odstraníme ignorované tagy
        for tag in soup.find_all(IGNORED_TAGS):
            tag.decompose()

        # Najdeme hlavní obsah
        content: Tag | None = None
        for selector in CONTENT_SELECTORS:
            content = soup.select_one(selector)
            if content:
                break
        if content is None:
            content = soup.body

        if content is None:
            return None

        lines: list[str] = []

        # Nadpis stránky
        h1 = soup.find("h1")
        if h1:
            lines.append(f"# {h1.get_text(strip=True)}")
            lines.append(f"Zdroj: {url}")
            lines.append("")

        # Zkusíme Q&A extrakci z <details> accordion
        details_tags = content.find_all("details")
        if len(details_tags) >= 2:
            lines.append("## Časté dotazy\n")
            for detail in details_tags:
                summary = detail.find("summary")
                question = summary.get_text(strip=True) if summary else ""
                if summary:
                    summary.decompose()
                answer = detail.get_text(separator=" ", strip=True)
                answer = re.sub(r"\s{2,}", " ", answer)
                if question:
                    lines.append(f"Q: {question}")
                    lines.append(f"A: {answer}")
                    lines.append("")
            return "\n".join(lines)

        # Fallback: strukturovaný text dle nadpisů H2/H3 + odstavců
        for element in content.find_all(["h1", "h2", "h3", "h4", "p", "li", "dt", "dd"]):
            tag_name = element.name
            text = element.get_text(separator=" ", strip=True)
            text = re.sub(r"\s{2,}", " ", text)

            if not text or len(text) < 3:
                continue

            if tag_name == "h1":
                lines.append(f"# {text}")
            elif tag_name == "h2":
                lines.append(f"\n## {text}")
            elif tag_name in ("h3", "h4"):
                lines.append(f"\n### {text}")
            elif tag_name == "dt":
                lines.append(f"\nQ: {text}")
            elif tag_name == "dd":
                lines.append(f"A: {text}")
            else:
                lines.append(text)

        result = "\n".join(lines).strip()
        return result if len(result) > 200 else None

    def _save_faq_file(self, url: str, text: str) -> Path | None:
        """
        Uloží FAQ text jako .txt soubor do data/raw/.

        Název souboru: faq_<slug-prvnich-40-znaku>_<8-znaku-hash>.txt
        Hash zabrání kolizím u URL se stejným prefixem (subpages FAQ sekce).
        """
        import hashlib
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)

        url_path = urlparse(url).path.strip("/").replace("/", "_")
        slug = re.sub(r"[^\w\-]", "_", url_path)[:40]
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        dest = config.RAW_DIR / f"faq_{slug}_{url_hash}.txt"

        if dest.exists():
            return None  # Vrátíme None = soubor nebyl nově vytvořen

        dest.write_text(text, encoding="utf-8")
        logger.info(f"FAQ uloženo: [cyan]{dest.name}[/cyan]")
        return dest

    # ── Download PDF ──────────────────────────────────────────────────────────

    def _download_pdf(self, url: str) -> Path | None:
        """Stáhne PDF soubor do data/raw/."""
        from src.ingestion.downloader import download_pdf as _dl
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        self._polite_delay()
        return _dl(url, config.RAW_DIR)

    # ── Crawl jádro ──────────────────────────────────────────────────────────

    def _crawl_page(self, url: str) -> list[str]:
        """
        Stáhne jednu stránku a vrátí nově nalezené PDF URL.

        Vedlejší efekt: pokud je stránka FAQ, uloží ji jako .txt.
        """
        if not self._is_allowed(url):
            self.result.pages_skipped += 1
            return []

        self._polite_delay()
        resp = self._fetch(url)
        if resp is None:
            return []

        # Kontrola Content-Type – přeskočíme binární obsah
        ct = resp.headers.get("Content-Type", "")
        if "html" not in ct:
            return []

        self.result.pages_crawled += 1

        try:
            soup = BeautifulSoup(resp.content, "lxml")
        except Exception as exc:
            logger.warning(f"BS4 parse error {url}: {exc}")
            return []

        # Extrakce PDF linků
        page_pdfs = self._extract_pdf_links(soup, url)
        new_pdfs = [p for p in page_pdfs if p not in self.found_pdfs]
        self.found_pdfs.update(page_pdfs)

        if new_pdfs:
            logger.info(
                f"[green]+{len(new_pdfs)} PDF[/green] nalezeno na "
                f"[blue]{url.replace(BASE_URL, '')}[/blue]"
            )

        # FAQ extrakce
        if self.save_faq and self._is_faq_page(soup, url):
            text = self._extract_faq_text(soup, url)
            if text:
                faq_path = self._save_faq_file(url, text)
                if faq_path:
                    self.result.faq_files.append(faq_path)

        return new_pdfs

    # ── Hlavní crawl smyčka ───────────────────────────────────────────────────

    def run(self) -> ScrapeResult:
        """Spustí kompletní scraping pipeline."""

        console.print(Panel.fit(
            "[bold cyan]Raiffeisenbank Web Scraper[/bold cyan]\n"
            f"[dim]Base URL: {BASE_URL}[/dim]\n"
            f"[dim]Max stránek: {self.max_pages} | "
            f"Delay: {self.delay_min}–{self.delay_max}s | "
            f"Dry-run: {self.dry_run}[/dim]",
            border_style="cyan",
        ))

        # ── Krok 1: Sitemap ──────────────────────────────────────────────────
        console.print("\n[bold]Krok 1/4:[/bold] Načítám sitemap.xml…")
        all_urls = self._load_sitemap_urls()
        if not all_urls:
            logger.error("Žádné URL ze sitemapy – ukončuji")
            return self.result

        priority_urls, rest_urls = self._prioritize_urls(all_urls)
        console.print(
            f"  [green]✓[/green] {len(all_urls)} URL | "
            f"prioritní: [bold]{len(priority_urls)}[/bold] | "
            f"ostatní: {len(rest_urls)}"
        )

        # ── Krok 2: Crawl prioritních stránek ────────────────────────────────
        console.print(f"\n[bold]Krok 2/4:[/bold] Crawl {len(priority_urls)} prioritních stránek…")

        crawl_queue: deque[str] = deque(priority_urls)
        # Přidáme zbytek na konec (pro případ, že prioritní stránky nestačí)
        crawl_queue.extend(rest_urls)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Crawluji stránky…",
                total=min(self.max_pages, len(crawl_queue)),
            )

            while crawl_queue and self.result.pages_crawled < self.max_pages:
                url = crawl_queue.popleft()

                if url in self.visited:
                    continue
                self.visited.add(url)

                progress.update(
                    task,
                    advance=1,
                    description=f"[dim]{url.replace(BASE_URL, '')[:55]}[/dim]",
                )
                self._crawl_page(url)

        console.print(
            f"  [green]✓[/green] Stránek zpracováno: {self.result.pages_crawled} | "
            f"nalezeno PDF URL: [bold]{len(self.found_pdfs)}[/bold] | "
            f"FAQ souborů: {len(self.result.faq_files)}"
        )

        # ── Krok 3: Uložení sources.txt ──────────────────────────────────────
        console.print("\n[bold]Krok 3/4:[/bold] Ukládám data/sources.txt…")
        self.result.pdf_urls = sorted(self.found_pdfs)
        self._save_sources_txt()
        console.print(
            f"  [green]✓[/green] {len(self.result.pdf_urls)} PDF URL zapsáno do "
            f"[cyan]{config.DATA_DIR / 'sources.txt'}[/cyan]"
        )

        # ── Krok 4: Stahování PDF ────────────────────────────────────────────
        if self.download_pdfs and not self.dry_run:
            console.print(
                f"\n[bold]Krok 4/4:[/bold] Stahuji "
                f"{len(self.result.pdf_urls)} PDF souborů…"
            )
            downloaded = 0
            skipped = 0
            errors = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "Stahuji PDF…", total=len(self.result.pdf_urls)
                )

                for pdf_url in self.result.pdf_urls:
                    name = Path(urlparse(pdf_url).path).name
                    progress.update(task, advance=1, description=f"[dim]{name}[/dim]")

                    dest = config.RAW_DIR / name
                    if dest.exists():
                        skipped += 1
                        continue

                    path = self._download_pdf(pdf_url)
                    if path:
                        downloaded += 1
                    else:
                        errors += 1

            console.print(
                f"  [green]✓[/green] Staženo: {downloaded} | "
                f"přeskočeno (existující): {skipped} | "
                f"chyby: {errors}"
            )
        elif self.dry_run:
            console.print(
                "\n[yellow]Dry-run:[/yellow] Stahování přeskočeno. "
                "PDF URL jsou zapsána do sources.txt."
            )
        else:
            console.print("\n[dim]Krok 4/4: Stahování přeskočeno (--no-download)[/dim]")

        # ── Závěrečný výpis ──────────────────────────────────────────────────
        self._print_summary()
        return self.result

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save_sources_txt(self) -> None:
        """
        Zapíše nalezené PDF URL do data/sources.txt.
        Zachová strukturu: komentáře s kategoriemi.
        """
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Roztřídíme URL do kategorií dle cesty
        categories: dict[str, list[str]] = {
            "Sazebníky a ceníky": [],
            "Obchodní podmínky a VOP": [],
            "Úrokové sazby": [],
            "Produktové a informační listy": [],
            "Hypotéky": [],
            "Karty": [],
            "Pojištění": [],
            "Investice a fondy": [],
            "Ostatní": [],
        }

        category_patterns: list[tuple[str, list[str]]] = [
            ("Sazebníky a ceníky",           ["cenik", "sazebni"]),
            ("Obchodní podmínky a VOP",       ["podminky", "vop", "ramcova"]),
            ("Úrokové sazby",                 ["urokove-sazby", "ul-depozita", "ul-uvery"]),
            ("Produktové a informační listy", ["pi/", "produktovy", "informacni-list"]),
            ("Hypotéky",                      ["hypoteka", "hypo"]),
            ("Karty",                         ["/karty/", "/kk-", "/kreditni"]),
            ("Pojištění",                     ["pojisteni"]),
            ("Investice a fondy",             ["investic", "fond", "certifikat", "dluhopis"]),
        ]

        for pdf_url in self.result.pdf_urls:
            path_lower = urlparse(pdf_url).path.lower()
            assigned = False
            for cat, patterns in category_patterns:
                if any(p in path_lower for p in patterns):
                    categories[cat].append(pdf_url)
                    assigned = True
                    break
            if not assigned:
                categories["Ostatní"].append(pdf_url)

        lines = [
            "# Automaticky vygenerováno scraperem scripts/scrape_rb.py",
            f"# Nalezeno: {len(self.result.pdf_urls)} PDF souborů z {BASE_URL}",
            "# Jeden URL na řádek. Řádky začínající # jsou komentáře.",
            "",
        ]

        for cat, urls in categories.items():
            if urls:
                lines.append(f"# ── {cat} ({len(urls)}) ──────────────────")
                lines.extend(sorted(urls))
                lines.append("")

        dest = config.DATA_DIR / "sources.txt"
        dest.write_text("\n".join(lines), encoding="utf-8")

    def _print_summary(self) -> None:
        """Vypíše finální statistiky do konzole."""
        table = Table(title="Výsledky scrapingu", border_style="green", show_lines=True)
        table.add_column("Metrika", style="cyan")
        table.add_column("Hodnota", justify="right", style="bold")

        table.add_row("Zpracované stránky", str(self.result.pages_crawled))
        table.add_row("Přeskočené stránky", str(self.result.pages_skipped))
        table.add_row("Chyby", str(self.result.errors))
        table.add_row("Nalezené PDF URL", str(len(self.result.pdf_urls)))
        table.add_row("Stažené PDF soubory", str(len(list(config.RAW_DIR.glob("*.pdf")))))
        table.add_row("FAQ textové soubory", str(len(self.result.faq_files)))

        console.print()
        console.print(table)
        console.print()
        console.print(
            Panel.fit(
                f"[bold green]Scraping dokončen![/bold green]\n"
                f"  PDF URL: [cyan]{config.DATA_DIR / 'sources.txt'}[/cyan]\n"
                f"  Soubory: [cyan]{config.RAW_DIR}[/cyan]\n\n"
                f"Příští krok:\n"
                f"  [bold]python scripts/ingest.py --skip-download[/bold]",
                border_style="green",
            )
        )


# ---------------------------------------------------------------------------
# CLI vstupní bod
# ---------------------------------------------------------------------------

@app.command()
def main(
    max_pages: int = typer.Option(
        600, "--max-pages", "-m",
        help="Maximální počet stránek k procrawlování (pojistka).",
    ),
    delay: float = typer.Option(
        None, "--delay", "-d",
        help="Pevný delay v sekundách (přepíše výchozí 1–3 s rozsah).",
    ),
    delay_min: float = typer.Option(1.0, "--delay-min", help="Minimální delay (s)."),
    delay_max: float = typer.Option(3.0, "--delay-max", help="Maximální delay (s)."),
    no_download: bool = typer.Option(
        False, "--no-download",
        help="Najde a zaloguje PDF URL, ale nestáhne soubory.",
    ),
    no_faq: bool = typer.Option(
        False, "--no-faq",
        help="Přeskočí extrakci a ukládání FAQ stránek.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Pouze vypíše co by bylo staženo (sources.txt ano, PDF ne).",
    ),
) -> None:
    """
    Scraper pro rb.cz – hledá PDF dokumenty a FAQ stránky.

    Respektuje robots.txt a přidává zdvořilostní delay.
    Nalezené PDF stáhne do data/raw/ a URL zapíše do data/sources.txt.
    """
    if delay is not None:
        delay_min_val = delay
        delay_max_val = delay
    else:
        delay_min_val = delay_min
        delay_max_val = delay_max

    scraper = RBScraper(
        delay_min=delay_min_val,
        delay_max=delay_max_val,
        max_pages=max_pages,
        download_pdfs=not no_download,
        save_faq=not no_faq,
        dry_run=dry_run,
    )
    scraper.run()


if __name__ == "__main__":
    app()

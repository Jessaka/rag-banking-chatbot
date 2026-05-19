#!/usr/bin/env python3
"""
Playwright scraper pro JS-rendered produktové stránky rb.cz.

Proč Playwright a ne requests+BeautifulSoup (viz scrape_rb.py)?
  - rb.cz používá JavaScript komponenty: accordion FAQ, React produktové
    stránky, lazy-load content, cookie consent wall
  - requests+BS4 vidí pouze serverem renderovaný HTML (prázdné kontejnery)
  - Playwright spustí headless Chromium → plný JS rendering → celý obsah

Co scraper extrahuje:
  - Produktové stránky: hypotéky, účty, karty, půjčky, pojištění, investice
  - FAQ / Časté dotazy (dynamické accordion komponenty)
  - Podmínky produktů a sazebníky s JS-renderovaným obsahem

Výstup: data/raw/playwright_{kategorie}_{slug}.txt
  Každý soubor obsahuje metadata hlavičku + čistý text stránky.

Použití:
  python scripts/scrape_rb_playwright.py               # vše dle URL listu
  python scripts/scrape_rb_playwright.py --category hypoteky
  python scripts/scrape_rb_playwright.py --url https://www.rb.cz/osobni/hypoteky/hypoteka-na-bydleni
  python scripts/scrape_rb_playwright.py --urls-file data/js_pages.txt
  python scripts/scrape_rb_playwright.py --dry-run    # vypíše seznam URL bez scraping
  python scripts/scrape_rb_playwright.py --headed     # viditelný browser (debug)

Instalace Playwright:
  pip install playwright
  playwright install chromium   # stáhne ~150 MB headless Chromium
  # nebo: playwright install --with-deps chromium  (Ubuntu 22/24)

Požadavky prostředí:
  - Ubuntu ≤ 24.04, macOS, nebo Windows (Ubuntu 26+ zatím nepodporováno)
  - Playwright 1.44+ s Chromium browser
  - Pro Docker: FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

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

# ---------------------------------------------------------------------------
# Cílové URL pro JS scraping – produktové stránky rb.cz
# ---------------------------------------------------------------------------
# Skupiny jsou použity pro název výstupního souboru (kategorie).
# Jednotlivé URL jsou vybrány jako "landing pages" produktových sekcí
# a konkrétní produkty – ty mají nejbohatší JS-renderovaný obsah.

PRODUCT_URLS: dict[str, list[str]] = {
    "hypoteky": [
        "/osobni/hypoteky",
        "/osobni/hypoteky/hypoteka-na-bydleni",
        "/osobni/hypoteky/hypoteky-nabidka",
        "/osobni/hypoteky/hypoteka-s-nizsi-splatkou",
        "/osobni/hypoteky/odpovedna-hypoteka",
        "/osobni/hypoteky/jak-ziskat-hypoteku",
        "/osobni/hypoteky/refinancovani-hypoteky",
        "/osobni/hypoteky/americka-hypoteka",
    ],
    "ucty": [
        "/osobni/ucty",
        "/osobni/ucty/bezny-ucet",
        "/osobni/ucty/ekonto",
        "/osobni/ucty/chytry-ucet",
        "/osobni/ucty/aktivni-ucet",
        "/osobni/ucty/exkluzivni-ucet",
        "/osobni/ucty/sporici-ucet",
        "/osobni/ucty/studentsky-ucet",
        "/osobni/ucty/detsky-ucet",
        "/osobni/ucty/sluzby-k-uctum",
        "/podpora/cenik",
        "/informacni-servis/predsmluvni-dokumenty",
    ],
    "karty": [
        "/osobni/karty",
        "/osobni/karty/kreditni-karty",
        "/osobni/karty/platebni-karty",
        "/osobni/karty/debetni-karty",
        "/osobni/karty/virtualni-karta",
        "/osobni/karty/sluzby-ke-kartam",
        "/osobni/karty/sluzby-ke-kartam/pojisteni-ke-karte",
        "/osobni/ucty/sluzby-k-uctum/platebni-karty",
    ],
    "pujcky": [
        "/osobni/pujcky",
        "/osobni/pujcky/spotrebitelsky-uver",
        "/osobni/pujcky/kontokorent",
        "/osobni/pujcky/refinancovani",
        "/osobni/pujcky/pujcka-od-az-do",
    ],
    "pojisteni": [
        "/osobni/pojisteni",
        "/osobni/pojisteni/pojisteni-ke-karte",
        "/osobni/pojisteni/pojisteni-k-hypotece",
        "/osobni/pojisteni/cestovni-pojisteni",
        "/osobni/pojisteni/pojisteni-majetku",
        "/osobni/pojisteni/pojisteni-ke-stavajicim-produktum",
    ],
    "sporeni-investice": [
        "/osobni/sporeni-a-investice",
        "/osobni/sporeni-a-investice/sporeni",
        "/osobni/sporeni-a-investice/penzijni-sporeni",
        "/osobni/sporeni-a-investice/stavebni-sporeni",
        "/osobni/sporeni-a-investice/investice",
        "/osobni/sporeni-a-investice/investice/podilove-fondy",
        "/osobni/sporeni-a-investice/termined-vklad",
    ],
    "podpora-faq": [
        "/podpora",
        "/podpora/bezpecnost",
        "/osobni/ucty/sluzby-k-uctum/internetove-bankovnictvi/caste-dotazy",
        "/podpora/caste-dotazy",
    ],
    "informace": [
        "/informacni-servis/urokove-sazby",
        "/informacni-servis/dokumenty-ke-stazeni",
        "/informacni-servis/predsmluvni-dokumenty",
        "/informacni-servis/informacni-a-online-sluzby",
    ],
}

# ---------------------------------------------------------------------------
# Cookie consent – rb.cz cookie wall
# ---------------------------------------------------------------------------

# Název cookie pro souhlas – zjištěno z cookie-wall.js skriptů rb.cz
_CONSENT_COOKIE = {
    "name": "cookieConsent",
    "value": "true",
    "domain": ".rb.cz",
    "path": "/",
}

# Selektory pro tlačítko "Přijmout vše" / "Accept all"
_CONSENT_BUTTON_SELECTORS = [
    "button:has-text('Přijmout vše')",
    "button:has-text('Přijmout všechny')",
    "button:has-text('Souhlasím')",
    "button:has-text('Přijmout')",
    "[data-testid='cookie-accept-all']",
    ".cookie-consent__accept",
    "#onetrust-accept-btn-handler",
    ".js-cookie-accept",
]

# ---------------------------------------------------------------------------
# Selektory pro hlavní obsah
# ---------------------------------------------------------------------------

# Selektory obsahu v prioritním pořadí – specifické pro rb.cz Angular SPA.
# rb.cz nepoužívá <main>/<article> – hlavní obsah je v .page-wrapper/.content.
_CONTENT_SELECTORS = [
    ".page-wrapper",             # primární obsah produktových stránek rb.cz
    ".content",                  # obecný content blok
    ".content-block",            # blokový obsah
    ".additional-content",       # doplňkový obsah
    "main",                      # HTML5 fallback (některé podstránky)
    "[role='main']",
    "article",
    "#content",
    "app-root",                  # poslední záloha: celý Angular kořen
]

# Elementy k odstranění před extrakcí – Angular navigace rb.cz
_REMOVE_SELECTORS = [
    # Angular komponenty navigace
    "app-navigation", "app-header", "app-footer",
    ".main-nav", ".product-navigation", ".page-mega-footer",
    # Standardní HTML5 fallbacky
    "nav", "header", "footer",
    # Cookie / GDPR
    ".cookie-wall", ".cookie-banner", "#cookie-consent",
    "[data-cookiebanner]", ".cookieconsent",
    # Technické elementy
    "script", "style", "noscript",
    # Navigační drobečky a skip linky
    ".breadcrumb", ".breadcrumbs", "[aria-label='Breadcrumb']",
    ".back-to-top", ".skip-link",
    # Překryvné vrstvy a modály (nezobrazeny)
    ".popup-container", ".overlay",
]

# Selektory loading stavů – čekáme na jejich zmizení
_SPINNER_SELECTORS = [
    ".loading", ".spinner", ".skeleton", ".loader",
    "[class*='loading']", "[class*='spinner']", "[class*='skeleton']",
    "mat-progress-spinner", "mat-progress-bar",
    ".rb-spinner", "[data-loading]",
]

# Minimální délka textu která svědčí o úspěšném načtení obsahu (ne jen navigace)
_MIN_CONTENT_LENGTH = 300

# ---------------------------------------------------------------------------
# Datové struktury
# ---------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    url: str
    category: str
    slug: str
    text: str
    output_path: Path
    success: bool
    error: str = ""


@dataclass
class ScrapeSummary:
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[ScrapeResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# URL utility
# ---------------------------------------------------------------------------

def _url_to_slug(url: str) -> str:
    """Převede URL na bezpečný slug pro název souboru."""
    path = urlparse(url).path.strip("/").replace("/", "_")
    slug = re.sub(r"[^\w\-]", "_", path)
    return slug[:80] or "index"


def _get_category(url: str, product_urls: dict[str, list[str]]) -> str:
    """Vrátí kategorii pro URL dle mapy product_urls."""
    path = urlparse(url).path
    for category, urls in product_urls.items():
        for u in urls:
            if u in path or path in u:
                return category
    return "ostatni"


def _load_urls_from_sitemap(categories: list[str] | None = None) -> list[tuple[str, str]]:
    """
    Načte URL ze sitemapy rb.cz a přidá je k pevně definovaným URL.
    Vrátí seznam (url, kategorie) tuplů.

    Používá se pro auto-discovery nových stránek které nemusí být
    v pevném PRODUCT_URLS seznamu.
    """
    result: list[tuple[str, str]] = []
    try:
        resp = requests.get(
            f"{BASE_URL}/sitemap.xml",
            headers={"User-Agent": "Mozilla/5.0 (compatible; RAG-Banking-Scraper/1.0)"},
            timeout=15,
        )
        soup = BeautifulSoup(resp.content, "xml")
        for loc in soup.find_all("loc"):
            url = loc.text.strip()
            if not url.startswith(BASE_URL):
                continue
            # Filtrujeme anglické/ukrajinské mutace
            path = url.replace(BASE_URL, "")
            if path.startswith(("/en/", "/uk/")):
                continue
            # Zařadíme do kategorie
            cat = _get_category(url, PRODUCT_URLS)
            if categories and cat not in categories:
                continue
            result.append((url, cat))
    except Exception as exc:
        logger.warning(f"Sitemap načtení selhalo: {exc}")
    return result


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_extracted_text(raw: str) -> str:
    """
    Čistění textu extrahovaného z webové stránky.
      - Oprava mezislovních mezer (unicode)
      - Odstraní záhlaví/zápatí vzory
      - Normalizace prázdných řádků
    """
    # Nahradíme non-breaking spaces a jiné unicode whitespace
    text = raw.replace("\xa0", " ").replace("​", "").replace("­", "")
    # Odstraníme opakující se navigační texty
    patterns = [
        r"Přejít na obsah",
        r"Zpět na",
        r"www\.rb\.cz",
        r"Raiffeisenbank a\.s\.",
        r"©\s*\d{4}",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    # Normalizujeme whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_output_text(url: str, category: str, raw_text: str) -> str:
    """Sestaví výstupní text s metadatovou hlavičkou."""
    header = "\n".join([
        f"URL: {url}",
        f"Kategorie: {category}",
        f"Datum: {date.today().isoformat()}",
        f"Zdroj: Playwright (JS-rendered)",
        "",
        "=" * 60,
        "",
    ])
    return header + raw_text


# ---------------------------------------------------------------------------
# Playwright async scraping
# ---------------------------------------------------------------------------

async def _setup_browser_context(playwright):
    """
    Vytvoří browser kontext s čekou lokalizací a přednastavenými cookies
    pro cookie consent.

    Nastavení:
      - locale cs-CZ pro česky renderovaný obsah
      - timezone Europe/Prague
      - viewport 1280×800
      - user-agent moderní prohlížeč
      - přednastavené cookies pro přeskočení cookie wall
    """
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    context = await browser.new_context(
        locale="cs-CZ",
        timezone_id="Europe/Prague",
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )

    # Přednastavíme cookie consent aby se nezobrazoval banner.
    # Playwright vyžaduje buď "url" nebo "domain" – ne obě zároveň.
    # Používáme "domain" (s tečkou = platné pro všechny subdomény rb.cz).
    await context.add_cookies([
        _CONSENT_COOKIE,
        {"name": "OptanonAlertBoxClosed", "value": "1",   "domain": ".rb.cz", "path": "/"},
        {"name": "cookieconsent_status",  "value": "allow","domain": ".rb.cz", "path": "/"},
    ])

    return browser, context


async def _handle_cookie_consent(page) -> bool:
    """
    Pokusí se kliknout na tlačítko cookie consent.
    Vrátí True pokud bylo tlačítko nalezeno a kliknuto.
    """
    for selector in _CONSENT_BUTTON_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=1000):
                await button.click()
                await page.wait_for_timeout(500)
                logger.debug(f"Cookie consent kliknut: {selector}")
                return True
        except Exception:
            continue
    return False


async def _wait_for_spinners_gone(page, timeout_ms: int = 5000) -> None:
    """
    Čeká na zmizení všech loading spinnerů.
    Neblokuje pokud žádné spinnery nejsou přítomny.
    """
    for selector in _SPINNER_SELECTORS:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                await locator.wait_for(state="hidden", timeout=timeout_ms)
        except Exception:
            pass  # spinner nenalezen nebo timeout – pokračujeme


async def _wait_for_content(page, timeout_ms: int = 8000) -> str:
    """
    Čeká na načtení smysluplného obsahu v rb.cz-specifických selektorech.

    Prochází _CONTENT_SELECTORS a vrátí název prvního selektoru,
    který obsahuje alespoň _MIN_CONTENT_LENGTH znaků textu.
    Pokud žádný nevyhoví, vrátí None.
    """
    for selector in _CONTENT_SELECTORS:
        try:
            locator = page.locator(selector).first
            # Počkáme na viditelnost elementu
            await locator.wait_for(state="visible", timeout=timeout_ms)
            text = await locator.inner_text()
            if len(text.strip()) >= _MIN_CONTENT_LENGTH:
                logger.debug(f"Obsah nalezen v '{selector}' ({len(text)} znaků)")
                return selector
        except Exception:
            continue
    return None


async def _scroll_and_load(page) -> None:
    """
    Postupný scroll stránky pro aktivaci lazy-load komponent.

    Angular na rb.cz používá IntersectionObserver pro lazy loading –
    komponenty se inicializují teprve když vstoupí do viewportu.

    Strategie:
      1. Scrolluje dolů po 400px krocích s pauzou 200ms
      2. Čeká 500ms na inicializaci Angular komponent
      3. Vrátí scroll na začátek stránky
    """
    await page.evaluate("""
        async () => {
            const scrollStep = 400;
            const stepDelay = 200;
            const totalHeight = document.documentElement.scrollHeight;

            for (let y = 0; y < totalHeight; y += scrollStep) {
                window.scrollTo({ top: y, behavior: 'instant' });
                await new Promise(r => setTimeout(r, stepDelay));
            }
            // Krátká pauza pro dokončení Angular animací
            await new Promise(r => setTimeout(r, 500));
            window.scrollTo({ top: 0, behavior: 'instant' });
        }
    """)


async def _expand_interactive_content(page) -> None:
    """
    Expanze interaktivního obsahu Angular Material komponent:
      - Záložky (mat-tab): klikne na každou záložku pro načtení obsahu
      - Accordiony (mat-expansion-panel, details/summary): otevře je
      - show-more tlačítka: klikne pro zobrazení skrytého textu

    Každé kliknutí je obaleno try/except – selhání jednoho prvku
    neblokuje zpracování zbytku stránky.
    """
    # Angular Material záložky – každá záložka může mít jiný obsah
    tab_selectors = [
        "mat-tab-header button[role='tab']",
        ".mat-mdc-tab-label-container button[role='tab']",
        "[role='tablist'] [role='tab']",
    ]
    for tab_sel in tab_selectors:
        try:
            tabs = page.locator(tab_sel)
            count = await tabs.count()
            if count > 1:  # >1 = existují záložky k přepnutí
                for i in range(count):
                    try:
                        await tabs.nth(i).click(timeout=800)
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                break  # Nalezly se záložky, neprobíráme další selektory
        except Exception:
            continue

    # Angular Material expansion panels a HTML5 details
    accordion_selectors = [
        "mat-expansion-panel-header",
        "summary",
        "[aria-expanded='false']",
        ".accordion__trigger",
        ".accordion-toggle",
        "[class*='expansion-panel-header']",
    ]
    for acc_sel in accordion_selectors:
        try:
            panels = page.locator(acc_sel)
            count = await panels.count()
            for i in range(min(count, 15)):
                try:
                    panel = panels.nth(i)
                    if await panel.is_visible():
                        await panel.click(timeout=500)
                        await page.wait_for_timeout(150)
                except Exception:
                    pass
        except Exception:
            continue

    # "Zobrazit více" / "Show more" tlačítka
    showmore_selectors = [
        "button:has-text('Zobrazit více')",
        "button:has-text('Načíst více')",
        "button:has-text('Více informací')",
        "[class*='show-more']",
        "[class*='load-more']",
        ".additional-content-show-more button",
    ]
    for sm_sel in showmore_selectors:
        try:
            btn = page.locator(sm_sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def _extract_page_text(page, url: str) -> str:
    """
    Extrahuje čistý text z plně načtené stránky rb.cz (Angular SPA).

    Pořadí operací:
      1. Odstraní navigaci a boilerplate elementy
      2. Najde selector s nejdelším textem z _CONTENT_SELECTORS
      3. Fallback: celý body text
    """
    # Odebereme navigaci a boilerplate přes DOM manipulation
    await page.evaluate("""
        (selectors) => {
            selectors.forEach(sel => {
                try {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                } catch(e) {}
            });
        }
    """, _REMOVE_SELECTORS)

    # Najdeme selector s nejbohatším obsahem
    best_text = ""
    best_selector = "body"
    for selector in _CONTENT_SELECTORS:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            text = await locator.inner_text()
            stripped = text.strip()
            if len(stripped) > len(best_text):
                best_text = stripped
                best_selector = selector
                if len(best_text) >= _MIN_CONTENT_LENGTH * 3:
                    break  # Dost obsahu – nehledáme dál
        except Exception:
            continue

    logger.debug(f"Nejlepší selektor: '{best_selector}' ({len(best_text)} znaků)")

    # Fallback: celý body
    if len(best_text) < _MIN_CONTENT_LENGTH:
        try:
            best_text = await page.locator("body").inner_text()
        except Exception:
            best_text = await page.evaluate("() => document.body.innerText || ''")

    return _clean_extracted_text(best_text)


async def scrape_page(
    page,
    url: str,
    category: str,
    output_dir: Path,
    delay: float = 2.0,
    skip_existing: bool = True,
) -> ScrapeResult:
    """
    Scrapuje jednu stránku a uloží výsledek do souboru.

    Args:
        page:         Playwright Page objekt.
        url:          URL ke scrapování.
        category:     Kategorie pro název souboru.
        output_dir:   Adresář pro výstupní soubory.
        delay:        Zdvořilostní čekání po načtení (v sekundách).
        skip_existing: Přeskočí stránky které již byly scrapovány.
    """
    slug = _url_to_slug(url)
    output_path = output_dir / f"playwright_{category}_{slug}.txt"

    if skip_existing and output_path.exists():
        return ScrapeResult(
            url=url, category=category, slug=slug,
            text="", output_path=output_path,
            success=True, error="skipped"
        )

    try:
        # Krok 1: Navigace – čekáme na DOMContentLoaded (Angular SSR HTML)
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Krok 2: Čekáme na Angular hydration + JS komponenty
        # networkidle = žádné síťové požadavky po 500ms → Angular hotov
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            # Angular může stále inicializovat – dáme mu extra čas
            await page.wait_for_timeout(3_000)

        # Krok 3: Cookie consent (záloha – cookies obvykle stačí)
        await _handle_cookie_consent(page)

        # Krok 4: Čekáme na zmizení loading spinnerů
        await _wait_for_spinners_gone(page, timeout_ms=5_000)

        # Krok 5: Čekáme na konkrétní content selektor s dostatkem textu
        found_selector = await _wait_for_content(page, timeout_ms=6_000)
        if not found_selector:
            logger.debug(f"Žádný content selektor nenalezl {_MIN_CONTENT_LENGTH}+ znaků, pokračuji…")

        # Krok 6: Scroll pro aktivaci lazy-load Angular komponent
        await _scroll_and_load(page)

        # Krok 7: Čekáme na nově načtené komponenty po scrollu
        await _wait_for_spinners_gone(page, timeout_ms=3_000)

        # Krok 8: Rozbalíme záložky, accordiony, show-more tlačítka
        await _expand_interactive_content(page)

        # Krok 9: Extrakce textu
        text = await _extract_page_text(page, url)

        if len(text) < 100:
            return ScrapeResult(
                url=url, category=category, slug=slug,
                text="", output_path=output_path,
                success=False, error="příliš málo textu (<100 znaků)"
            )

        # Sestavení a uložení výstupu
        output_dir.mkdir(parents=True, exist_ok=True)
        full_text = _build_output_text(url, category, text)
        output_path.write_text(full_text, encoding="utf-8")

        # Zdvořilostní pauza
        await asyncio.sleep(delay)

        return ScrapeResult(
            url=url, category=category, slug=slug,
            text=text, output_path=output_path, success=True
        )

    except Exception as exc:
        error_msg = str(exc)[:200]
        logger.warning(f"Chyba při scrapování {url}: {error_msg}")
        return ScrapeResult(
            url=url, category=category, slug=slug,
            text="", output_path=output_path,
            success=False, error=error_msg
        )


async def run_scraping(
    urls: list[tuple[str, str]],   # (url, category)
    output_dir: Path,
    delay_min: float = 1.5,
    delay_max: float = 3.5,
    skip_existing: bool = True,
    headed: bool = False,
) -> ScrapeSummary:
    """
    Hlavní async scraping smyčka.

    Spouští jediný browser context pro celý batch URL
    (efektivnější než restart browseru pro každou stránku).
    """
    import random

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright není nainstalovaný.\n"
            "Spusťte: pip install playwright && playwright install chromium"
        )

    summary = ScrapeSummary(total=len(urls))

    async with async_playwright() as playwright:
        browser, context = await _setup_browser_context(playwright)
        page = await context.new_page()

        # Blokujeme zbytečné zdroje pro rychlejší načítání
        await page.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,mp4,webp}",
            lambda route: route.abort()
        )
        # Sledování konzolových chyb pro debug
        page.on("console", lambda msg: logger.debug(f"[JS] {msg.text[:100]}") if msg.type == "error" else None)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scrapuji stránky…", total=len(urls))

            for url, category in urls:
                slug = _url_to_slug(url)
                progress.update(
                    task,
                    advance=1,
                    description=f"[dim]{url.replace(BASE_URL, '')[:55]}[/dim]",
                )

                delay = random.uniform(delay_min, delay_max)
                result = await scrape_page(
                    page, url, category, output_dir,
                    delay=delay, skip_existing=skip_existing,
                )
                summary.results.append(result)

                if result.error == "skipped":
                    summary.skipped += 1
                elif result.success:
                    summary.succeeded += 1
                    char_count = len(result.text)
                    logger.info(
                        f"[green]✓[/green] {category}/{slug[:30]} "
                        f"({char_count:,} znaků)"
                    )
                else:
                    summary.failed += 1
                    logger.warning(f"[red]✗[/red] {url}: {result.error[:60]}")

        await context.close()
        await browser.close()

    return summary


# ---------------------------------------------------------------------------
# Výpis výsledků
# ---------------------------------------------------------------------------

def _print_summary(summary: ScrapeSummary) -> None:
    table = Table(title="Výsledky Playwright scrapingu", border_style="green")
    table.add_column("Metrika", style="cyan")
    table.add_column("Hodnota", justify="right", style="bold")

    table.add_row("Celkem URL", str(summary.total))
    table.add_row("Úspěšně scrapováno", str(summary.succeeded))
    table.add_row("Přeskočeno (existuje)", str(summary.skipped))
    table.add_row("Selhalo", str(summary.failed))

    console.print(table)

    # Výpis selhání
    failed = [r for r in summary.results if not r.success and r.error != "skipped"]
    if failed:
        console.print("\n[yellow]Selhané stránky:[/yellow]")
        for r in failed[:10]:
            console.print(f"  [red]✗[/red] {r.url}: {r.error[:80]}")


# ---------------------------------------------------------------------------
# CLI vstupní bod
# ---------------------------------------------------------------------------

@app.command()
def main(
    category: str = typer.Option(
        None, "--category", "-c",
        help=f"Kategorie ke scrapování: {', '.join(PRODUCT_URLS.keys())}",
    ),
    url: str = typer.Option(
        None, "--url", "-u",
        help="Jednorázové scrapování konkrétní URL.",
    ),
    urls_file: Path = typer.Option(
        None, "--urls-file",
        help="Soubor s URL (jeden na řádek).",
    ),
    output_dir: Path = typer.Option(
        config.RAW_DIR,
        "--output-dir", "-o",
        help="Výstupní adresář pro .txt soubory.",
    ),
    delay_min: float = typer.Option(1.5, "--delay-min", help="Min. delay mezi stránkami (s)."),
    delay_max: float = typer.Option(3.5, "--delay-max", help="Max. delay mezi stránkami (s)."),
    no_skip: bool = typer.Option(False, "--no-skip", help="Přescrapuje i existující soubory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Vypíše seznam URL bez scrapování."),
    headed: bool = typer.Option(False, "--headed", help="Viditelný browser (pro debug)."),
) -> None:
    """
    Playwright scraper pro JS-rendered produktové stránky rb.cz.

    Extrahuje text z dynamicky načítaného obsahu (React komponenty,
    accordion FAQ, lazy-load sekce) a ukládá do data/raw/ jako .txt.
    """
    # Ověření Playwright instalace
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        console.print(
            "[red]✗ Playwright není nainstalovaný.[/red]\n\n"
            "Spusťte:\n"
            "  [bold]pip install playwright[/bold]\n"
            "  [bold]playwright install chromium[/bold]\n\n"
            "Poznámka: Playwright vyžaduje Ubuntu ≤ 24.04, macOS nebo Windows.\n"
            "Pro Docker: [italic]FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy[/italic]"
        )
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            "[bold cyan]Raiffeisenbank Playwright Scraper[/bold cyan]\n"
            "[dim]JS-rendered produktové stránky → data/raw/playwright_*.txt[/dim]",
            border_style="cyan",
        )
    )

    # Sestavení seznamu URL
    target_urls: list[tuple[str, str]] = []

    if url:
        cat = category or _get_category(url, PRODUCT_URLS) or "ostatni"
        target_urls = [(url if url.startswith("http") else BASE_URL + url, cat)]

    elif urls_file and urls_file.exists():
        lines = urls_file.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                u = line if line.startswith("http") else BASE_URL + line
                cat = category or _get_category(u, PRODUCT_URLS) or "ostatni"
                target_urls.append((u, cat))

    else:
        # Pevně definované URL z PRODUCT_URLS
        for cat, urls_list in PRODUCT_URLS.items():
            if category and cat != category:
                continue
            for u in urls_list:
                full_url = BASE_URL + u if not u.startswith("http") else u
                target_urls.append((full_url, cat))

    if not target_urls:
        console.print("[yellow]Žádné URL k scrapování.[/yellow]")
        raise typer.Exit()

    # Deduplikace
    seen: set[str] = set()
    target_urls = [(u, c) for u, c in target_urls if u not in seen and not seen.add(u)]

    console.print(f"Celkem URL: [bold]{len(target_urls)}[/bold]")
    if category:
        console.print(f"Kategorie: [bold]{category}[/bold]")
    console.print(f"Výstup: [cyan]{output_dir}[/cyan]")
    console.print()

    if dry_run:
        console.print("[yellow]Dry-run – pouze seznam URL:[/yellow]")
        for u, c in target_urls:
            console.print(f"  [{c}] {u}")
        return

    # Spuštění async scrapingu
    try:
        summary = asyncio.run(
            run_scraping(
                urls=target_urls,
                output_dir=output_dir,
                delay_min=delay_min,
                delay_max=delay_max,
                skip_existing=not no_skip,
                headed=headed,
            )
        )
    except Exception as exc:
        err = str(exc)
        if "Executable doesn't exist" in err or "not found" in err.lower() or "playwright install" in err.lower():
            console.print(
                "[red]✗ Playwright browser není nainstalovaný.[/red]\n\n"
                "Spusťte:\n"
                "  [bold]playwright install chromium[/bold]\n"
                "  nebo: [bold]playwright install --with-deps chromium[/bold]\n\n"
                "Poznámka: Vyžaduje Ubuntu ≤ 24.04, macOS nebo Windows.\n"
                "Docker: [italic]FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy[/italic]"
            )
        else:
            console.print(f"[red]✗ Chyba: {err[:200]}[/red]")
        raise typer.Exit(code=1)

    console.print()
    _print_summary(summary)

    if summary.succeeded > 0:
        console.print(
            Panel.fit(
                f"[bold green]Scraping dokončen![/bold green]\n"
                f"  {summary.succeeded} souborů uloženo do [cyan]{output_dir}[/cyan]\n\n"
                f"Příští krok:\n"
                f"  [bold]python scripts/ingest.py --skip-download[/bold]",
                border_style="green",
            )
        )


if __name__ == "__main__":
    app()

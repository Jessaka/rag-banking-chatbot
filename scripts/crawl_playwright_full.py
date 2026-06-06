"""Rekurzivní Playwright crawler pro celou sekci osobních financí rb.cz.

Spouštění v Docker (dávkový režim):
  docker run --rm --memory=3g \\
    -v /home/kalin/rag-banking-chatbot:/app \\
    mcr.microsoft.com/playwright/python:v1.44.0-jammy \\
    bash -c "pip install playwright==1.44.0 -q && \\
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \\
    python3 /app/scripts/crawl_playwright_full.py --batch 0"

Dávky:
  --batch 0  Investice a spoření
  --batch 1  Pojištění
  --batch 2  Hypotéky
  --batch 3  Účty
  --batch 4  Kreditní karty
  --batch 5  Půjčky
  --batch 6  Online služby
  --batch 7  Bezpečnost
  --batch 8  Důležité informace
"""

import argparse
import pathlib
import re
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

SEED_BATCHES = [
    # 0: Investice a spoření
    ['https://www.rb.cz/osobni/zhodnoceni-uspor/investice',
     'https://www.rb.cz/osobni/zhodnoceni-uspor/sporeni'],
    # 1: Pojištění - všechny typy
    ['https://www.rb.cz/osobni/pojisteni'],
    # 2: Hypotéky - všechny typy
    ['https://www.rb.cz/osobni/hypoteky'],
    # 3: Účty - všechny typy
    ['https://www.rb.cz/osobni/ucty'],
    # 4: Kreditní karty + debetní karty
    ['https://www.rb.cz/osobni/kreditni-karty',
     'https://www.rb.cz/osobni/ucty/sluzby-k-uctum/platebni-karty'],
    # 5: Půjčky
    ['https://www.rb.cz/osobni/pujcky'],
    # 6: Online služby
    ['https://www.rb.cz/osobni/ucty/sluzby-k-uctum',
     'https://www.rb.cz/bankovni-identita',
     'https://www.rb.cz/informacni-servis/asistentka-raia',
     'https://www.rb.cz/osobni/ucty/sluzby-k-uctum/internetove-bankovnictvi',
     'https://www.rb.cz/osobni/ucty/sluzby-k-uctum/mobilni-bankovnictvi'],
    # 7: Bezpečnost
    ['https://www.rb.cz/bezpecne-bankovnictvi'],
    # 8: Důležité informace
    ['https://www.rb.cz/rbclub',
     'https://www.rb.cz/dulezite-informace',
     'https://www.rb.cz/o-nas/kontakty',
     'https://www.rb.cz/dulezite-informace/reklamace',
     'https://www.rb.cz/dulezite-informace/urokove-sazby'],
]

SKIP = [
    'kariera', 'pro-media', 'tiskove-zpravy', 'vyrocni-zpravy',
    'investori', 'vedeni', 'login', 'prihlasit', '.pdf',
    'marketingove-akce', 'pravidla-', 'cookie', 'sitemap',
    'en/', 'uk/', '/promo/', '/test/', '/attachments/',
    'aktuality-201', 'aktuality-202',
]

import os
OUT_DIR = pathlib.Path(os.environ.get('OUT_DIR', str(pathlib.Path(__file__).parent.parent / 'data' / 'raw')))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# No page limit — crawl all pages in the batch
MAX_PAGES = 99_999

BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-sync',
    '--disable-translate',
    '--disable-default-apps',
    '--mute-audio',
]
RESTART_EVERY = 20  # Restart browser every N pages to prevent memory leaks


def make_browser_and_page(p):
    browser = p.chromium.launch(headless=True, args=BROWSER_ARGS)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        locale='cs-CZ',
        java_script_enabled=True,
    )
    ctx.add_cookies([{'name': 'cookieConsent', 'value': 'true', 'domain': '.rb.cz', 'path': '/'}])
    return browser, ctx.new_page()


def is_valid_rb_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.netloc not in ('rb.cz', 'www.rb.cz'):
        return False
    if any(s in url.lower() for s in SKIP):
        return False
    return True


def crawl_batch(batch_idx: int) -> int:
    seeds = SEED_BATCHES[batch_idx]
    batch_name = {
        0: 'Investice+Spoření', 1: 'Pojištění', 2: 'Hypotéky',
        3: 'Účty', 4: 'Kreditní karty', 5: 'Půjčky',
        6: 'Online služby', 7: 'Bezpečnost', 8: 'Důležité informace',
    }.get(batch_idx, f'Dávka {batch_idx}')

    print(f'\n=== Dávka {batch_idx}: {batch_name} ===', flush=True)
    print(f'Seeds: {seeds}', flush=True)

    visited: set[str] = set()
    queue: list[str] = list(seeds)
    saved = 0

    with sync_playwright() as p:
        browser, page = make_browser_and_page(p)
        pages_since_restart = 0

        while queue and saved < MAX_PAGES:
            url = queue.pop(0)
            url = url.split('?')[0].split('#')[0].rstrip('/')
            if url in visited:
                continue
            visited.add(url)

            if not is_valid_rb_url(url):
                continue

            # Periodic browser restart to free memory
            if pages_since_restart >= RESTART_EVERY:
                try:
                    browser.close()
                except Exception:
                    pass
                browser, page = make_browser_and_page(p)
                pages_since_restart = 0
                print(f'  [browser restart at {saved} pages]', flush=True)

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(1200)
                text = page.inner_text('body')

                if len(text) < 400:
                    continue

                slug = re.sub(r'[^a-z0-9]', '_', url.split('rb.cz/')[-1].lower())[:70]
                slug = slug.strip('_') or 'index'
                out_path = OUT_DIR / f'rb_pwfull_{slug}.txt'
                out_path.write_text(
                    f'URL: {url}\nDatum: 2026-06-04\n====\n{text[:15000]}',
                    encoding='utf-8'
                )
                saved += 1
                pages_since_restart += 1
                print(f'OK ({saved}): {url[-70:]}', flush=True)

                # Collect internal links — only same-section links for focus
                links = page.eval_on_selector_all('a[href]', 'els => els.map(e => e.href)')
                for link in links:
                    link = link.split('?')[0].split('#')[0].rstrip('/')
                    if link and link not in visited and link not in queue and is_valid_rb_url(link):
                        queue.append(link)

                time.sleep(0.4)

            except Exception as e:
                err_msg = str(e).split('\n')[0][:80]
                print(f'ERR: {url[-55:]}: {err_msg}', flush=True)
                if any(x in str(e) for x in ('crashed', 'Target closed', 'Target page')):
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser, page = make_browser_and_page(p)
                    pages_since_restart = 0
                    print('  [browser restarted after crash]', flush=True)
                    # Re-queue crashed URL
                    if url not in visited:
                        queue.insert(0, url)

        try:
            browser.close()
        except Exception:
            pass

    print(f'Dávka {batch_idx} hotova: {saved} stránek uloženo', flush=True)
    return saved


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, default=None,
                        help='Číslo dávky (0-8). Bez parametru spustí všechny.')
    args = parser.parse_args()

    if args.batch is not None:
        if args.batch < 0 or args.batch >= len(SEED_BATCHES):
            print(f'Neplatná dávka {args.batch}. Dostupné: 0-{len(SEED_BATCHES)-1}')
            sys.exit(1)
        total = crawl_batch(args.batch)
        total_files = len(list(OUT_DIR.glob('rb_pwfull_*.txt')))
        print(f'\nHotovo: {total} stránek, celkem v data/raw: {total_files} souborů')
    else:
        grand_total = 0
        for i in range(len(SEED_BATCHES)):
            grand_total += crawl_batch(i)
        total_files = len(list(OUT_DIR.glob('rb_pwfull_*.txt')))
        print(f'\nVšechny dávky hotovy: {grand_total} stránek, celkem: {total_files} souborů')

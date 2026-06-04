"""Rekurzivní Playwright crawler pro celou sekci osobních financí rb.cz.

Spouštění v Docker:
  docker run --rm \
    -v /home/kalin/rag-banking-chatbot:/app \
    mcr.microsoft.com/playwright/python:v1.44.0-jammy \
    bash -c "cd /app && python3 scripts/crawl_playwright_full.py"
"""

from playwright.sync_api import sync_playwright
import pathlib, time, re
from urllib.parse import urlparse

SEED_URLS = [
    'https://www.rb.cz/osobni',
    'https://www.rb.cz/bezpecne-bankovnictvi',
    'https://www.rb.cz/bankovni-identita',
    'https://www.rb.cz/rbclub',
    'https://www.rb.cz/dulezite-informace',
]

SKIP = [
    'kariera', 'pro-media', 'tiskove-zpravy', 'vyrocni-zpravy',
    'investori', 'vedeni', 'login', 'prihlasit', '.pdf',
    'marketingove-akce', 'pravidla-', 'cookie', 'sitemap',
    'en/', 'uk/', '/promo/', '/test/', '/attachments/',
]

MAX_PAGES = 500
OUT_DIR = pathlib.Path('/app/data/raw')
OUT_DIR.mkdir(parents=True, exist_ok=True)

visited = set()
queue = list(SEED_URLS)
saved = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        locale='cs-CZ',
    )
    # Accept cookies silently
    ctx.add_cookies([{'name': 'cookieConsent', 'value': 'true', 'domain': '.rb.cz', 'path': '/'}])
    page = ctx.new_page()

    while queue and saved < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if any(s in url.lower() for s in SKIP):
            continue
        parsed = urlparse(url)
        if parsed.netloc not in ('rb.cz', 'www.rb.cz'):
            continue

        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(1500)
            text = page.inner_text('body')

            if len(text) < 500:
                continue

            slug = re.sub(r'[^a-z0-9]', '_', url.split('rb.cz/')[-1].lower())[:70]
            slug = slug.strip('_') or 'index'
            out_path = OUT_DIR / f'rb_pwfull_{slug}.txt'
            out_path.write_text(
                f'URL: {url}\nDatum: 2026-06-04\n====\n{text[:15000]}',
                encoding='utf-8'
            )
            saved += 1
            print(f'OK ({saved}/{MAX_PAGES}): {url[-70:]}', flush=True)

            # Najdi všechny interní linky
            links = page.eval_on_selector_all(
                'a[href]', 'els => els.map(e => e.href)'
            )
            for link in links:
                link = link.split('?')[0].split('#')[0].rstrip('/')
                if (link and
                        link not in visited and
                        link not in queue and
                        'rb.cz' in link and
                        not any(s in link.lower() for s in SKIP)):
                    queue.append(link)

            time.sleep(0.5)

        except Exception as e:
            print(f'ERR: {url[-60:]}: {e}', flush=True)

    browser.close()

print(f'Hotovo: {saved} stránek uloženo do {OUT_DIR}', flush=True)

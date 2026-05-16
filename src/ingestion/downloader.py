"""
Stahování PDF dokumentů z rb.cz a jiných zdrojů.

Podporuje:
- seznam URL z konfigurace nebo souboru
- přeskočení již stažených souborů (idempotentní)
- ověření MIME typu
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from tqdm import tqdm

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maximální velikost jednoho PDF (50 MB)
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
_REQUEST_TIMEOUT = 30
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0


def _url_to_filename(url: str) -> str:
    """Převede URL na bezpečný název souboru; pro kolize přidá hash."""
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name.endswith(".pdf"):
        name = hashlib.md5(url.encode()).hexdigest()[:12] + ".pdf"
    return name


def download_pdf(url: str, dest_dir: Path) -> Path | None:
    """
    Stáhne jeden PDF soubor do dest_dir.

    Args:
        url:      Plné URL vedoucí na PDF.
        dest_dir: Adresář, kam se soubor uloží.

    Returns:
        Cesta k uloženému souboru, nebo None při chybě.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = _url_to_filename(url)
    dest_path = dest_dir / filename

    if dest_path.exists():
        logger.info(f"Přeskakuji (již existuje): [cyan]{filename}[/cyan]")
        return dest_path

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RAG-Banking-Bot/1.0; "
            "+https://github.com/your-repo)"
        )
    }

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type and attempt == _RETRY_ATTEMPTS:
                logger.warning(
                    f"Neočekávaný Content-Type '{content_type}' pro {url}"
                )

            total_size = int(response.headers.get("Content-Length", 0))
            if total_size > _MAX_FILE_SIZE_BYTES:
                logger.error(f"Soubor příliš velký ({total_size} B): {url}")
                return None

            with open(dest_path, "wb") as f, tqdm(
                total=total_size or None,
                unit="B",
                unit_scale=True,
                desc=filename,
                leave=False,
            ) as bar:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bar.update(len(chunk))

            logger.info(f"Staženo: [green]{filename}[/green] ({dest_path.stat().st_size:,} B)")
            return dest_path

        except requests.RequestException as exc:
            logger.warning(f"Pokus {attempt}/{_RETRY_ATTEMPTS} selhal pro {url}: {exc}")
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY * attempt)

    logger.error(f"Stažení selhalo po {_RETRY_ATTEMPTS} pokusech: {url}")
    if dest_path.exists():
        dest_path.unlink()
    return None


def download_all(urls: list[str], dest_dir: Path) -> list[Path]:
    """
    Stáhne seznam PDF dokumentů.

    Args:
        urls:     Seznam URL k PDF souborům.
        dest_dir: Cílový adresář.

    Returns:
        Seznam cest ke stažených souborům.
    """
    logger.info(f"Zahajuji stahování {len(urls)} dokumentů do '{dest_dir}'")
    downloaded: list[Path] = []

    for url in urls:
        path = download_pdf(url, dest_dir)
        if path is not None:
            downloaded.append(path)

    logger.info(
        f"Dokončeno: {len(downloaded)}/{len(urls)} souborů úspěšně staženo"
    )
    return downloaded


def load_urls_from_file(filepath: Path) -> list[str]:
    """
    Načte seznam URL z textového souboru (jeden URL na řádek).
    Řádky začínající # jsou komentáře.
    """
    if not filepath.exists():
        return []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]

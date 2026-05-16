"""
Parsování a čištění PDF dokumentů.

Používá PyMuPDF (fitz) jako primární parser.
Pro PDF s neobvyklým layoutem (tabulky, sloupce) se jako záloha použije pdfplumber.

Extrahuje text se zachováním metadat:
  - název souboru
  - číslo stránky
  - celkový počet stránek
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.documents import Document
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Čistící funkce pro český text z PDF
# ---------------------------------------------------------------------------

def _fix_hyphenation(text: str) -> str:
    """Spojí slova rozdělená pomlčkou na konci řádku."""
    return re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)


def _normalize_whitespace(text: str) -> str:
    """Nahradí vícenásobné mezery/nové řádky jednotnými."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_headers_footers(text: str) -> str:
    """
    Odstraní typické záhlaví/zápatí bankovních PDF (čísla stránek,
    'Raiffeisenbank a.s.', datum tisku, atd.).
    """
    patterns = [
        r"Raiffeisenbank a\.s\.\s*",
        r"Strana \d+ z \d+",
        r"^\d+\s*$",                     # Samotné číslo stránky
        r"Platnost od \d{1,2}\.\d{1,2}\.\d{4}",
        r"www\.rb\.cz",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.MULTILINE | re.IGNORECASE)
    return text


def _clean_text(raw: str) -> str:
    """Pipeline čistění: hyphenation → headers/footers → whitespace."""
    text = _fix_hyphenation(raw)
    text = _remove_headers_footers(text)
    text = _normalize_whitespace(text)
    return text


# ---------------------------------------------------------------------------
# Hlavní parsovací funkce
# ---------------------------------------------------------------------------

def parse_pdf_pymupdf(pdf_path: Path) -> list[Document]:
    """
    Parsuje PDF pomocí PyMuPDF (fitz).

    Vrací seznam Document objektů, každý odpovídá jedné stránce.
    Metadata obsahují: source, page, total_pages, file_name.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("Nainstalujte pymupdf: pip install pymupdf")

    documents: list[Document] = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.error(f"Nelze otevřít {pdf_path.name}: {exc}")
        return []

    total_pages = len(doc)
    logger.info(f"Parsuju '{pdf_path.name}' ({total_pages} stránek) [PyMuPDF]")

    for page_num, page in enumerate(doc, start=1):
        raw_text = page.get_text("text")
        cleaned = _clean_text(raw_text)

        if len(cleaned) < 50:
            # Stránka je pravděpodobně obrázek nebo prázdná
            logger.debug(f"  Stránka {page_num}: příliš málo textu, přeskakuji")
            continue

        documents.append(
            Document(
                page_content=cleaned,
                metadata={
                    "source": str(pdf_path),
                    "file_name": pdf_path.name,
                    "page": page_num,
                    "total_pages": total_pages,
                },
            )
        )

    doc.close()
    logger.info(f"  → {len(documents)} stránek extrahováno")
    return documents


def parse_pdf_pdfplumber(pdf_path: Path) -> list[Document]:
    """
    Záložní parser pomocí pdfplumber – lepší pro tabulky a vícesloupcové layouty.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("Nainstalujte pdfplumber: pip install pdfplumber")

    documents: list[Document] = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            total_pages = len(pdf.pages)
            logger.info(
                f"Parsuju '{pdf_path.name}' ({total_pages} stránek) [pdfplumber]"
            )

            for page_num, page in enumerate(pdf.pages, start=1):
                raw_text = page.extract_text() or ""
                cleaned = _clean_text(raw_text)

                if len(cleaned) < 50:
                    continue

                documents.append(
                    Document(
                        page_content=cleaned,
                        metadata={
                            "source": str(pdf_path),
                            "file_name": pdf_path.name,
                            "page": page_num,
                            "total_pages": total_pages,
                        },
                    )
                )
    except Exception as exc:
        logger.error(f"pdfplumber selhal na {pdf_path.name}: {exc}")

    logger.info(f"  → {len(documents)} stránek extrahováno")
    return documents


def parse_pdf(pdf_path: Path, fallback: bool = True) -> list[Document]:
    """
    Parsuje PDF s automatickým fallbackem:
      1. Pokus: PyMuPDF (rychlý, spolehlivý pro lineární text)
      2. Fallback: pdfplumber (pomalejší, lepší pro tabulky)

    Args:
        pdf_path: Cesta k PDF souboru.
        fallback: Pokud True a PyMuPDF vrátí málo textu, zkusí pdfplumber.
    """
    docs = parse_pdf_pymupdf(pdf_path)

    if fallback and len(docs) == 0:
        logger.warning(
            f"PyMuPDF nevytěžil text z '{pdf_path.name}', zkouším pdfplumber…"
        )
        docs = parse_pdf_pdfplumber(pdf_path)

    return docs


def parse_all_pdfs(pdf_dir: Path) -> list[Document]:
    """
    Parsuje všechny PDF soubory v adresáři.

    Returns:
        Sloučený seznam všech Document objektů ze všech PDF.
    """
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"V adresáři '{pdf_dir}' nejsou žádné PDF soubory")
        return []

    all_docs: list[Document] = []
    for pdf_path in pdf_files:
        docs = parse_pdf(pdf_path)
        all_docs.extend(docs)

    logger.info(f"Celkem extrahováno {len(all_docs)} stránek z {len(pdf_files)} PDF")
    return all_docs

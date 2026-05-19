"""
Parsování a čištění PDF dokumentů.

Strategie pro ceníkové PDF (Raiffeisenbank):
  - PyMuPDF: extrakce čistého textu (rychlý, zachytí všechna čísla)
  - pdfplumber: detekce a extrakce tabulkové struktury
  - Hybridní parser: pdfplumber pro tabulky + PyMuPDF pro zbytek stránky

Klíčový problém ceníků: horizontálně sloučené buňky (merged cells)
  Příklad: "v ceně" platí pro 3 tarify, ale PDF zobrazuje text jednou
  uprostřed sloučené buňky → pdfplumber vrátí hodnotu jen v 1. sloupci,
  ostatní jako None.

Řešení:
  1. Horizontální propagace: None buňky v řádku vyplníme hodnotou
     ze stejného řádku (sloučená buňka má stejnou hodnotu ve všech sloupcích)
  2. Tabulky konvertujeme do Markdown, čímž zachováme strukturu pro RAG
  3. Ignorujeme zápatí tabulek (poznámky pod čarou jako řádky)
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
    """Odstraní typické záhlaví/zápatí bankovních PDF."""
    patterns = [
        r"Raiffeisenbank a\.s\.\s*",
        r"Strana \d+ z \d+",
        r"^\d+\s*$",
        r"Platnost od \d{1,2}\.\d{1,2}\.\d{4}",
        r"www\.rb\.cz",
        r"Zpět na obsah",
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
# Tabulkové pomocné funkce
# ---------------------------------------------------------------------------

# Hodnoty které se v ceníkových tabulkách typicky opakují ve sloučených buňkách
_MERGED_CELL_INDICATORS = frozenset({
    "v ceně", "zdarma", "nelze použít", "na vyžádání",
    "dle tarifu", "individuálně", "není účtováno",
})

# Vzor pro rozpoznání zápatí tabulky (poznámky pod čarou)
_FOOTNOTE_PATTERN = re.compile(r"^\s*[\d]+\)\s*|^Pozn[.:]|^Poznámka")


def _is_footnote_row(row: list) -> bool:
    """Vrátí True pokud řádek vypadá jako poznámka pod čarou (ne datový řádek)."""
    first = str(row[0] or "").strip()
    return bool(_FOOTNOTE_PATTERN.match(first))


def _fill_horizontal_merged_cells(table: list[list]) -> list[list]:
    """
    Propaguje hodnoty horizontálně přes None buňky v rámci jednoho řádku.

    Pravidlo: propagujeme POUZE pokud má řádek právě 1 neprázdnou buňku.
    To je spolehlivý příznak horizontálně sloučené buňky (merged cell) —
    PDF zobrazí text jednou uprostřed, parser ho přiřadí k jednomu sloupci.

    Příklady:
      ['v ceně', None, None]    → ['v ceně', 'v ceně', 'v ceně']   ✓
      ['zdarma', None, None]    → ['zdarma', 'zdarma', 'zdarma']   ✓
      ['49 Kč', 'zdarma', None] → beze změny (různé hodnoty)       ✓
    """
    result = []
    for row in table:
        non_null = [c for c in row if c is not None and str(c).strip()]
        null_count = sum(1 for c in row if c is None)

        if null_count > 0 and len(non_null) == 1:
            # Jediná hodnota → merged cell přes celý řádek
            fill_val = non_null[0]
            row = [fill_val if c is None else c for c in row]

        result.append(row)
    return result


def _table_to_markdown(table: list[list]) -> str:
    """
    Konvertuje 2D seznam buněk tabulky do Markdown formátu.

    Markdown je ideální pro RAG chunking:
      - LLM rozumí sloupcové struktuře
      - Čísla jsou zachována v kontextu sloupce (tarif/produkt)
      - Snadné vyhledávání v BM25 (zachová "49 Kč" jako celek)

    Zápatí tabulek (poznámky pod čarou s "1) ...", "Pozn:") jsou přidána
    jako prostý text za tabulku — jsou odstraněna z tabulkové struktury,
    ale zachována jako text protože obvykle obsahují důležité Kč hodnoty.

    Příklad výstupu:
      Název položky | AKTIVNÍ účet | CHYTRÝ účet | EXKLUZIVNÍ účet
      --- | --- | --- | ---
      1. Cena | 49 Kč | zdarma | zdarma

      1) Pro EXKLUZIVNÍ účet znamená, že výše vkladů ... min. 1 500 000 Kč
    """
    if not table:
        return ""

    # Aplikujeme opravu merged cells
    table = _fill_horizontal_merged_cells(table)

    md_rows: list[str] = []
    footnote_lines: list[str] = []

    header = table[0]
    col_count = len(header)

    # Přeskočíme zápatí stránky maskující se jako tabulka (prázdný header + číslo stránky)
    header_values = [str(h or "").strip() for h in header]
    if not any(header_values):
        return ""

    # Záhlaví tabulky
    header_cells = [str(h or "").replace("\n", " ").strip() for h in header]
    md_rows.append(" | ".join(header_cells))
    md_rows.append(" | ".join(["---"] * col_count))

    # Vzor pro zápatí stránky (www.rb.cz + číslo stránky)
    _page_footer = re.compile(r"^www\.", re.IGNORECASE)

    for row in table[1:]:
        stripped = [str(c or "").strip() for c in row]
        non_empty = [s for s in stripped if s]

        # Přeskočíme prázdné řádky a zápatí stránky (www.rb.cz | 3)
        if not non_empty:
            continue
        if any(_page_footer.match(s) for s in non_empty):
            continue

        if _is_footnote_row(row):
            # Zápatí: zachováme jako prostý text (obsahuje Kč hodnoty)
            note = str(row[0] or "").replace("\n", " ").strip()
            if note:
                footnote_lines.append(note)
        elif len(set(non_empty)) == 1 and len(non_empty) > 1:
            # Section header: všechny buňky mají stejný obsah (propagovaný)
            # → zobrazíme jako standalone řádek, ne jako datový řádek tabulky
            md_rows.append(non_empty[0])
        else:
            cells = [str(c or "").replace("\n", " ").strip() for c in row]
            md_rows.append(" | ".join(cells))

    result = "\n".join(md_rows)
    if footnote_lines:
        result += "\n\n" + "\n".join(footnote_lines)

    return result


# ---------------------------------------------------------------------------
# Hybridní parser: pdfplumber (tabulky) + PyMuPDF (text)
# ---------------------------------------------------------------------------

def _extract_page_hybrid(
    fitz_page,
    plumber_page,
    page_num: int,
    total_pages: int,
    pdf_path: Path,
) -> Document | None:
    """
    Extrahuje obsah jedné stránky kombinací pdfplumber (tabulky) a PyMuPDF (text).

    Pipeline:
      1. pdfplumber detekuje tabulky a jejich bounding boxy
      2. Tabulky konvertujeme do Markdown (se správnou propagací merged cells)
      3. PyMuPDF text MIMO tabulky zachytí běžný text
      4. Výsledek: [text mimo tabulky] + [Markdown tabulky]

    Proč hybridní přístup?
      - pdfplumber detekuje tabulkové struktury přesněji než PyMuPDF
      - PyMuPDF zachytí všechna čísla (není závislý na detekci rámečků)
      - Kombinace eliminuje slepé skvrny obou parserů
    """
    # --- Krok 1: Detekce tabulek pdfplumber ---
    tables_data: list[tuple] = []  # (bbox, markdown_text)
    table_bboxes: list[tuple] = []

    try:
        detected = plumber_page.find_tables()
        for t in detected:
            rows = t.extract()
            if not rows or len(rows) < 2:
                continue
            md = _table_to_markdown(rows)
            if md:
                tables_data.append((t.bbox, md))
                table_bboxes.append(t.bbox)
    except Exception as exc:
        logger.debug(f"pdfplumber tabulky stránka {page_num}: {exc}")

    # --- Krok 2: PyMuPDF text mimo tabulky ---
    try:
        if table_bboxes:
            # Filtrujeme bloky textu které leží MIMO detekované tabulky
            blocks = fitz_page.get_text("blocks")
            non_table_blocks: list[str] = []

            for block in blocks:
                bx0, by0, bx1, by1, block_text = block[:5]
                block_text = str(block_text).strip()
                if not block_text:
                    continue

                # Kontrola překryvu s jakoukoliv tabulkou
                in_table = False
                for (tx0, ty0, tx1, ty1) in table_bboxes:
                    # Toleranční zóna ±5 px
                    if bx0 >= tx0 - 5 and by0 >= ty0 - 5 and bx1 <= tx1 + 5 and by1 <= ty1 + 5:
                        in_table = True
                        break

                if not in_table:
                    non_table_blocks.append(block_text)

            prose_text = "\n".join(non_table_blocks)
        else:
            prose_text = fitz_page.get_text("text")

    except Exception as exc:
        logger.debug(f"PyMuPDF text stránka {page_num}: {exc}")
        prose_text = fitz_page.get_text("text")

    # --- Krok 3: Sestavení výsledného textu ---
    parts: list[str] = []

    cleaned_prose = _clean_text(prose_text)
    if cleaned_prose:
        parts.append(cleaned_prose)

    for _bbox, md in tables_data:
        if md:
            parts.append(md)

    full_text = "\n\n".join(parts).strip()

    if len(full_text) < 50:
        return None

    return Document(
        page_content=full_text,
        metadata={
            "source": str(pdf_path),
            "file_name": pdf_path.name,
            "page": page_num,
            "total_pages": total_pages,
            "has_tables": len(tables_data) > 0,
            "table_count": len(tables_data),
        },
    )


# ---------------------------------------------------------------------------
# Hlavní parsovací funkce
# ---------------------------------------------------------------------------

def parse_pdf_hybrid(pdf_path: Path) -> list[Document]:
    """
    Hybridní parser: pdfplumber pro tabulky + PyMuPDF pro text.

    Výrazně lepší než čistý PyMuPDF nebo pdfplumber pro ceníkové PDF:
      - Zachytí strukturu tabulek (sloupcové hodnoty správně přiřazeny)
      - Opraví horizontální merged cells (v ceně, zdarma)
      - Konvertuje tabulky do Markdown pro lepší RAG retrieval

    Doporučeno pro: ceníky, sazebníky, tabulkové podmínky produktů.
    """
    try:
        import fitz
        import pdfplumber
    except ImportError as e:
        raise ImportError(f"Chybí závislost: {e}. Nainstalujte: pip install pymupdf pdfplumber")

    documents: list[Document] = []

    try:
        fitz_doc = fitz.open(str(pdf_path))
        total_pages = len(fitz_doc)
    except Exception as exc:
        logger.error(f"Nelze otevřít {pdf_path.name}: {exc}")
        return []

    logger.info(f"Parsuju '{pdf_path.name}' ({total_pages} stránek) [hybrid]")

    try:
        with pdfplumber.open(str(pdf_path)) as plumber_doc:
            for page_num in range(1, total_pages + 1):
                fitz_page = fitz_doc[page_num - 1]
                plumber_page = plumber_doc.pages[page_num - 1]

                doc = _extract_page_hybrid(
                    fitz_page, plumber_page, page_num, total_pages, pdf_path
                )
                if doc:
                    documents.append(doc)
                else:
                    logger.debug(f"  Stránka {page_num}: prázdná nebo obrázek, přeskakuji")
    except Exception as exc:
        logger.error(f"Hybridní parser selhal na {pdf_path.name}: {exc}")
    finally:
        fitz_doc.close()

    logger.info(f"  → {len(documents)} stránek extrahováno")
    return documents


def parse_pdf_pymupdf(pdf_path: Path) -> list[Document]:
    """
    PyMuPDF parser – rychlý, zachytí všechna čísla, ale bez tabulkové struktury.
    Vhodný pro lineární text (podmínky, FAQ, smlouvy).
    """
    try:
        import fitz
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
                    "has_tables": False,
                    "table_count": 0,
                },
            )
        )

    doc.close()
    logger.info(f"  → {len(documents)} stránek extrahováno")
    return documents


def parse_pdf_pdfplumber(pdf_path: Path) -> list[Document]:
    """
    pdfplumber fallback parser.
    Používá se pouze pokud PyMuPDF neextrahuje žádný text (obrázková PDF).
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
                            "has_tables": False,
                            "table_count": 0,
                        },
                    )
                )
    except Exception as exc:
        logger.error(f"pdfplumber selhal na {pdf_path.name}: {exc}")

    logger.info(f"  → {len(documents)} stránek extrahováno")
    return documents


def parse_pdf(pdf_path: Path, fallback: bool = True) -> list[Document]:
    """
    Parsuje PDF s výběrem strategie dle typu dokumentu:

      1. Pokud název obsahuje klíčová slova ceníku → hybridní parser
         (tabulky správně strukturované, merged cells opraveny)
      2. Jinak → PyMuPDF (rychlý, lineární text)
      3. Fallback → pdfplumber (pokud PyMuPDF neextrahuje nic)

    Args:
        pdf_path: Cesta k PDF souboru.
        fallback:  Pokud True a primární parser vrátí málo textu, zkusí zálohu.
    """
    # Detekce ceníkových PDF dle názvu souboru
    name_lower = pdf_path.name.lower()
    is_pricelist = any(kw in name_lower for kw in (
        "cenik", "ceník", "sazebnik", "sazebník", "porovnani", "porovnání",
        "tarif", "priloha", "příloha",
    ))

    if is_pricelist:
        docs = parse_pdf_hybrid(pdf_path)
        if docs:
            return docs
        # Fallback na PyMuPDF pokud hybridní selže
        logger.warning(
            f"Hybridní parser neextrahoval text z '{pdf_path.name}', zkouším PyMuPDF…"
        )

    docs = parse_pdf_pymupdf(pdf_path)

    if fallback and len(docs) == 0:
        logger.warning(
            f"PyMuPDF nevytěžil text z '{pdf_path.name}', zkouším pdfplumber…"
        )
        docs = parse_pdf_pdfplumber(pdf_path)

    return docs


def parse_txt(txt_path: Path) -> list[Document]:
    """
    Parsuje .txt soubor (Playwright scraped page nebo FAQ extrakce).

    Rozpozná metadata hlavičku scrape_rb_playwright.py a přeskočí ji:
      URL: https://www.rb.cz/...
      Kategorie: hypoteky
      Datum: 2026-05-19
      Zdroj: Playwright (JS-rendered)

      ============================================================

      [vlastní textový obsah stránky]

    Vrátí jeden Document za celý soubor s metadaty source/file_name/url.
    """
    try:
        raw = txt_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Nelze číst {txt_path.name}: {exc}")
        return []

    # Extrahujeme URL z hlavičky pro metadata
    url_match = re.search(r"^URL:\s*(.+)$", raw, re.MULTILINE)
    url = url_match.group(1).strip() if url_match else ""

    # Přeskočíme metadata hlavičku – Playwright scraper ji odděluje linií ====
    sep_match = re.search(r"^={3,}$", raw, re.MULTILINE)
    if sep_match:
        content = raw[sep_match.end():].strip()
    else:
        # FAQ scraper / prostý text – odstraníme pouze metadata řádky
        metadata_pattern = re.compile(r"^(URL|Zdroj|Kategorie|Datum):\s*.+$", re.MULTILINE)
        content = metadata_pattern.sub("", raw).strip()

    content = _clean_text(content)

    if len(content) < 50:
        logger.debug(f"  {txt_path.name}: příliš málo textu, přeskakuji")
        return []

    logger.debug(f"  {txt_path.name}: {len(content)} znaků extrahováno")
    return [Document(
        page_content=content,
        metadata={
            "source": str(txt_path),
            "file_name": txt_path.name,
            "page": 1,
            "total_pages": 1,
            "has_tables": False,
            "table_count": 0,
            "url": url,
        },
    )]


def parse_all_documents(doc_dir: Path) -> list[Document]:
    """
    Parsuje všechny PDF a .txt soubory v adresáři.

    PDF: hybridní parser (ceníky) nebo PyMuPDF + pdfplumber fallback.
    TXT: načte text a přeskočí metadata hlavičku Playwright scraperu.

    Returns:
        Sloučený seznam Document objektů ze všech souborů.
    """
    pdf_files = sorted(doc_dir.glob("*.pdf"))
    txt_files = [f for f in sorted(doc_dir.glob("*.txt")) if f.name != ".gitkeep"]

    if not pdf_files and not txt_files:
        logger.warning(f"V adresáři '{doc_dir}' nejsou žádné PDF ani TXT soubory")
        return []

    all_docs: list[Document] = []

    for pdf_path in pdf_files:
        all_docs.extend(parse_pdf(pdf_path))

    for txt_path in txt_files:
        all_docs.extend(parse_txt(txt_path))

    logger.info(
        f"Celkem extrahováno {len(all_docs)} dokumentů "
        f"z {len(pdf_files)} PDF + {len(txt_files)} TXT"
    )
    return all_docs


# Alias pro zpětnou kompatibilitu (ingest.py volá parse_all_pdfs)
parse_all_pdfs = parse_all_documents

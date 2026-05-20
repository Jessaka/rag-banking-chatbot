"""Structured pricing row extraction from real PDF tables.

This pipeline intentionally avoids creating pricing rows from free-form/OCR-like
text. It reads table cells extracted by pdfplumber, normalizes likely pricing
columns, validates rows, and persists deterministic JSONL records used by the
PricingRetriever.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import config
from src.ingestion.enterprise import classify_business_category, classify_document_type, classify_pricing_type
from src.utils.logger import get_logger

logger = get_logger(__name__)

VALUE_RE = re.compile(r"\b(?:zdarma|v ceně|[0-9][\d\s]*(?:[,.]\d+)?\s*(?:Kč|CZK|%))\b", re.IGNORECASE)
PERIOD_RE = re.compile(r"\b(měsíčně|mesicne|ročně|rocne|denně|denne|jednorázově|jednorazove|za\s+měsíc|za\s+mesic|za\s+rok)\b", re.IGNORECASE)
CURRENCY_RE = re.compile(r"\b(Kč|CZK|%)\b", re.IGNORECASE)
BROKEN_SPACING_RE = re.compile(r"\b\w\s+\w\s+\w\s+\w\b")
BLACKLIST_RE = re.compile(
    r"pozn\.?|podmín|podmin|kreditní\s+obrat|kreditni\s+obrat|aktiv\w*\s+využív\w*|aktiv\w*\s+vyuziv\w*|"
    r"transakce|minimální\s+vklad|minimalni\s+vklad|příjem\s+na\s+účet|prijem\s+na\s+ucet|"
    r"splnění\s+podmínek|splneni\s+podminek|bonus|akc\w*|poznámka|poznamka",
    re.IGNORECASE,
)
THRESHOLD_FEE_TYPE_RE = re.compile(r"obrat|příjem|prijem|vklad|kredit|transakce", re.IGNORECASE)


@dataclass
class PricingRow:
    product_name: str
    fee_type: str
    fee_value: str
    currency: str
    period: str
    conditions: str
    source_url: str
    source_file: str
    page: int
    table_index: int
    row_index: int
    title: str
    section_title: str
    category: str
    document_type: str
    pricing_type: str
    confidence: float
    raw_cells: list[str]


def _clean_cell(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\xa0", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_broken_row(cells: list[str]) -> bool:
    text = " ".join(cells)
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return True
    single_ratio = sum(1 for t in tokens if len(t.strip(".,;:()[]{}|")) == 1) / len(tokens)
    return single_ratio > 0.28 or bool(BROKEN_SPACING_RE.search(text))


def _has_value(cells: list[str]) -> bool:
    return any(VALUE_RE.search(cell) for cell in cells)


def _extract_value(text: str) -> str:
    match = VALUE_RE.search(text)
    return match.group(0).strip() if match else ""


def _numeric_fee_value(value: str) -> float | None:
    if not value or re.search(r"zdarma|v ceně", value, re.IGNORECASE):
        return 0.0
    match = re.search(r"[0-9][\d\s]*(?:[,.]\d+)?", value)
    if not match:
        return None
    normalized = match.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _extract_currency(value: str) -> str:
    match = CURRENCY_RE.search(value)
    cur = match.group(1) if match else ""
    return "CZK" if cur.lower() == "kč" else cur.upper()


def _extract_period(*parts: str) -> str:
    match = PERIOD_RE.search(" ".join(parts))
    return match.group(1) if match else ""


def _is_blacklisted_label(text: str) -> bool:
    return bool(BLACKLIST_RE.search(text or ""))


def _is_invalid_threshold_row(fee_type: str, fee_value: str) -> bool:
    numeric = _numeric_fee_value(fee_value)
    return numeric is not None and numeric > 10000 and bool(THRESHOLD_FEE_TYPE_RE.search(fee_type or ""))


def _confidence_score(product_name: str, fee_type: str, fee_value: str, currency: str, period: str) -> float:
    score = 0.0
    if product_name and not _is_blacklisted_label(product_name):
        score += 0.25
    if fee_type and not _is_blacklisted_label(fee_type):
        score += 0.25
    if fee_value and _numeric_fee_value(fee_value) is not None:
        score += 0.25
    if currency or re.search(r"zdarma|v ceně", fee_value or "", re.IGNORECASE):
        score += 0.15
    if period or any(k in (fee_type or "").lower() for k in ("měsí", "mesic", "roč", "roc", "jednor")):
        score += 0.10
    if _is_invalid_threshold_row(fee_type, fee_value):
        score -= 0.40
    return max(0.0, min(1.0, score))


def _is_pricing_table(headers: list[str], rows: list[list[str]]) -> bool:
    hay = " ".join(headers + [cell for row in rows[:8] for cell in row]).lower()
    return any(k in hay for k in ("poplatek", "cena", "kč", "czk", "zdarma", "vedení", "sazba", "tarif", "účet", "ucet"))


def _normalize_headers(header: list[str], width: int) -> list[str]:
    headers = [_clean_cell(h) for h in header]
    if len(headers) < width:
        headers += [""] * (width - len(headers))
    headers = headers[:width]
    if not any(headers):
        headers[0] = "Název položky"
    return [h or f"Sloupec {i+1}" for i, h in enumerate(headers)]


def _row_to_pricing_records(
    headers: list[str],
    cells: list[str],
    *,
    source_url: str,
    source_file: str,
    page: int,
    table_index: int,
    row_index: int,
    title: str,
) -> list[PricingRow]:
    if _is_broken_row(cells) or not _has_value(cells):
        return []

    records: list[PricingRow] = []
    first_cell = cells[0] if cells else ""
    header_text = " ".join(headers)
    row_text = " ".join(cells)
    category = classify_business_category(source_url, source_file, title, row_text, fallback="pricing")
    document_type = classify_document_type(source_url, title, source_file, fallback="pricing")

    for i, cell in enumerate(cells):
        value = _extract_value(cell)
        if not value:
            continue
        header = headers[i] if i < len(headers) else ""
        product_name = header if i > 0 and header.lower() not in {"cena", "poplatek", "hodnota"} else first_cell
        fee_type = first_cell if i > 0 else header
        if _is_blacklisted_label(product_name) or _is_blacklisted_label(fee_type):
            continue
        if _is_invalid_threshold_row(fee_type, value):
            continue
        currency = _extract_currency(value)
        period = _extract_period(cell, fee_type, header_text)
        confidence = _confidence_score(product_name, fee_type, value, currency, period)
        if confidence < 0.70:
            continue
        conditions = "; ".join(c for j, c in enumerate(cells) if j not in {0, i} and c and not _extract_value(c))
        if not product_name or not fee_type:
            continue
        records.append(PricingRow(
            product_name=product_name,
            fee_type=fee_type,
            fee_value=value,
            currency=currency,
            period=period,
            conditions=conditions,
            source_url=source_url,
            source_file=source_file,
            page=page,
            table_index=table_index,
            row_index=row_index,
            title=title,
            section_title=title,
            category=category,
            document_type="pricing" if document_type != "faq" else document_type,
            pricing_type=classify_pricing_type(source_url, title, product_name, fee_type, value),
            confidence=round(confidence, 3),
            raw_cells=cells,
        ))
    return records


def extract_pricing_rows_from_pdf(pdf_path: Path, metadata: dict | None = None, max_pages: int | None = None) -> list[PricingRow]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Structured pricing extraction vyžaduje pdfplumber") from exc

    metadata = metadata or {}
    source_url = metadata.get("url") or metadata.get("final_url") or f"file://{pdf_path}"
    title = metadata.get("title") or pdf_path.stem
    rows_out: list[PricingRow] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = pdf.pages[: max_pages or len(pdf.pages)]
            for page_num, page in enumerate(pages, start=1):
                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables):
                    cleaned_rows = [[_clean_cell(c) for c in row] for row in table if row]
                    cleaned_rows = [row for row in cleaned_rows if any(row)]
                    if len(cleaned_rows) < 2:
                        continue
                    width = max(len(row) for row in cleaned_rows)
                    normalized = [row + [""] * (width - len(row)) for row in cleaned_rows]
                    headers = _normalize_headers(normalized[0], width)
                    body = normalized[1:]
                    if not _is_pricing_table(headers, body):
                        continue
                    for row_index, cells in enumerate(body, start=1):
                        rows_out.extend(_row_to_pricing_records(
                            headers, cells,
                            source_url=source_url,
                            source_file=pdf_path.name,
                            page=page_num,
                            table_index=table_index,
                            row_index=row_index,
                            title=title,
                        ))
    except Exception as exc:
        logger.warning(f"Structured pricing extraction selhala pro {pdf_path.name}: {exc}")
    return rows_out


def load_document_metadata(pdf_dir: Path) -> dict[str, dict]:
    path = pdf_dir / "metadata.jsonl"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            out[row.get("filename", "")] = row
        except Exception:
            continue
    return out


def write_pricing_rows(rows: list[PricingRow], output_path: Path = config.PRICING_ROWS_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def _is_likely_pricing_pdf(pdf_path: Path, metadata: dict) -> bool:
    filename = pdf_path.name.lower()
    logical_name = filename.removeprefix("pricing_")
    hay = " ".join(str(metadata.get(k, "")) for k in ("url", "filename", "title", "category")).lower() + " " + logical_name
    include = any(k in hay for k in ("cenik", "ceník", "sazebnik", "sazebník", "sazební", "porovnani", "porovnání"))
    exclude = any(k in hay for k in ("statut", "pojistne-podminky", "vpp", "formular", "formulář", "prospekt", "sdeleni-klicovych-informaci"))
    return include and not exclude


def extract_pricing_rows_from_dir(
    pdf_dir: Path,
    output_path: Path = config.PRICING_ROWS_PATH,
    max_pages_per_pdf: int | None = config.PRICING_EXTRACT_MAX_PAGES_PER_PDF,
) -> dict:
    metadata_by_file = load_document_metadata(pdf_dir)
    all_rows: list[PricingRow] = []
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    scanned = 0
    for pdf_path in pdfs:
        metadata = metadata_by_file.get(pdf_path.name, {})
        if not _is_likely_pricing_pdf(pdf_path, metadata):
            continue
        scanned += 1
        all_rows.extend(extract_pricing_rows_from_pdf(pdf_path, metadata, max_pages=max_pages_per_pdf))
    write_pricing_rows(all_rows, output_path)
    stats = {
        "pdfs_total": len(pdfs),
        "pdfs_scanned": scanned,
        "rows": len(all_rows),
        "output_path": str(output_path),
        "top_products": Counter(r.product_name for r in all_rows).most_common(10),
        "top_fee_types": Counter(r.fee_type for r in all_rows).most_common(10),
    }
    logger.info(f"Structured pricing rows: {stats}")
    return stats

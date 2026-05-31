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
from src.ingestion.quality_filters import (
    filter_pricing_dataclass_rows,
    is_blacklisted_section,
    is_pricing_blacklisted_row,
    is_valid_pricing_row,
    PricingQualityStats,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLE_METHOD_PREFERENCE = ["pdfplumber", "camelot", "tabula"]
TABLE_MIN_ROWS = 2
_LAST_TABLE_EXTRACTION_METHOD: str | None = None
_LAST_TABLE_PAGES: list[int] = []

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
GENERIC_PRODUCT_RE = re.compile(r"^(?:cena|poplatek|hodnota|měsíčně|mesicne|ročně|rocne|vedení\s+(?:jednoho\s+)?běžného\s+účtu|vedeni\s+(?:jednoho\s+)?bezneho\s+uctu)$", re.IGNORECASE)


EXTRACTION_DEBUG = {
    "rejected_rows_count": 0,
    "orphan_rows": 0,
    "propagated_product_names": 0,
    "low_confidence_rows": 0,
    "grouped_table_rows": 0,
}


def _reset_extraction_debug() -> None:
    for key in EXTRACTION_DEBUG:
        EXTRACTION_DEBUG[key] = 0


def _debug_reject(reason: str) -> None:
    EXTRACTION_DEBUG["rejected_rows_count"] += 1
    if reason in {"orphan", "generic_product", "orphan_product_context"}:
        EXTRACTION_DEBUG["orphan_rows"] += 1
    if reason == "low_confidence":
        EXTRACTION_DEBUG["low_confidence_rows"] += 1


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
    if not cur and re.search(r"zdarma|v\s+ceně|v\s+cene", value or "", re.IGNORECASE):
        return "CZK"
    return "CZK" if cur.lower() == "kč" else cur.upper()


def _extract_period(*parts: str) -> str:
    match = PERIOD_RE.search(" ".join(parts))
    return match.group(1) if match else ""


def _is_blacklisted_label(text: str) -> bool:
    return bool(BLACKLIST_RE.search(text or ""))


def _is_invalid_threshold_row(fee_type: str, fee_value: str) -> bool:
    numeric = _numeric_fee_value(fee_value)
    return numeric is not None and numeric > 10000 and bool(THRESHOLD_FEE_TYPE_RE.search(fee_type or ""))


def _is_generic_product_name(product_name: str) -> bool:
    return not product_name or bool(GENERIC_PRODUCT_RE.match(product_name.strip())) or product_name.lower().startswith("sloupec ")


def _looks_like_product_header(cells: list[str]) -> str | None:
    non_empty = [c for c in cells if c.strip()]
    if not non_empty or _has_value(non_empty):
        return None
    first = non_empty[0].strip()
    if len(first) < 4 or _is_blacklisted_label(first) or GENERIC_PRODUCT_RE.match(first):
        return None
    if any(k in first.lower() for k in ("účet", "ucet", "ekonto", "konto", "tarif", "karta", "program")):
        return first
    return None


def _amount_from_value(value: str) -> str:
    if re.search(r"zdarma|v\s+ceně|v\s+cene", value or "", re.IGNORECASE):
        return "0"
    match = re.search(r"\d+(?:[\s.]\d{3})*(?:[,.]\d+)?", value or "")
    return match.group(0).replace(" ", "") if match else ""


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


def _has_min_table_rows(tables: list[list[list[str]]]) -> bool:
    return any(len(table) >= TABLE_MIN_ROWS for table in tables)


def _extract_tables_pdfplumber_only(path: str, max_pages: int | None = None) -> list[list[list[str]]]:
    global _LAST_TABLE_PAGES
    _LAST_TABLE_PAGES = []
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Structured pricing extraction vyžaduje pdfplumber") from exc

    tables_out: list[list[list[str]]] = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[: max_pages or len(pdf.pages)]
        for page_num, page in enumerate(pages, start=1):
            tables = page.extract_tables() or []
            for table in tables:
                cleaned_rows = [[_clean_cell(c) for c in row] for row in table if row]
                cleaned_rows = [row for row in cleaned_rows if any(row)]
                if cleaned_rows:
                    tables_out.append(cleaned_rows)
                    _LAST_TABLE_PAGES.append(page_num)
    return tables_out


def _extract_tables_pdfplumber(path: str, max_pages: int | None = None) -> list[list[list[str]]]:
    global _LAST_TABLE_EXTRACTION_METHOD, _LAST_TABLE_PAGES
    _LAST_TABLE_EXTRACTION_METHOD = None

    tables = _extract_tables_pdfplumber_only(path, max_pages=max_pages)
    if _has_min_table_rows(tables):
        _LAST_TABLE_EXTRACTION_METHOD = "pdfplumber"
        logger.info(f"table_extraction_method=pdfplumber path={path}")
        return tables

    _LAST_TABLE_PAGES = []
    tables = _extract_tables_camelot(path)
    if _has_min_table_rows(tables):
        _LAST_TABLE_EXTRACTION_METHOD = "camelot"
        _LAST_TABLE_PAGES = [0] * len(tables)
        logger.info(f"table_extraction_method=camelot path={path}")
        return tables

    tables = _extract_tables_tabula(path)
    if _has_min_table_rows(tables):
        _LAST_TABLE_EXTRACTION_METHOD = "tabula"
        _LAST_TABLE_PAGES = [0] * len(tables)
        logger.info(f"table_extraction_method=tabula path={path}")
        return tables

    logger.warning(f"table_extraction_method=none path={path}")
    return []


def _extract_tables_camelot(path: str) -> list[list[list[str]]]:
    try:
        import camelot
    except ImportError:
        logger.warning(f"Camelot není nainstalovaný, přeskakuji PDF table fallback path={path}")
        return []
    try:
        from camelot.errors import CamelotException
    except Exception:
        CamelotException = Exception

    try:
        camelot_tables = camelot.read_pdf(path, pages="all", flavor="lattice")
        if not camelot_tables:
            camelot_tables = camelot.read_pdf(path, pages="all", flavor="stream")
        tables_out: list[list[list[str]]] = []
        for table in camelot_tables:
            rows = table.df.fillna("").astype(str).values.tolist()
            cleaned_rows = [[_clean_cell(c) for c in row] for row in rows]
            cleaned_rows = [row for row in cleaned_rows if any(row)]
            if cleaned_rows:
                tables_out.append(cleaned_rows)
        return tables_out
    except CamelotException as exc:
        logger.warning(f"Camelot table extraction selhala path={path}: {exc}")
        return []


def _extract_tables_tabula(path: str) -> list[list[list[str]]]:
    try:
        import tabula
    except ImportError:
        logger.warning(f"Tabula není nainstalovaná, přeskakuji PDF table fallback path={path}")
        return []
    try:
        import pandas
    except ImportError:
        pandas = None
    try:
        dataframes = tabula.read_pdf(path, pages="all", multiple_tables=True) or []
        tables_out: list[list[list[str]]] = []
        for dataframe in dataframes:
            if pandas is not None and isinstance(dataframe, pandas.DataFrame):
                rows = dataframe.fillna("").astype(str).values.tolist()
            elif hasattr(dataframe, "fillna") and hasattr(dataframe, "values"):
                rows = dataframe.fillna("").values.tolist()
            else:
                rows = dataframe
            cleaned_rows = [[_clean_cell(c) for c in row] for row in rows if row is not None]
            cleaned_rows = [row for row in cleaned_rows if any(row)]
            if cleaned_rows:
                tables_out.append(cleaned_rows)
        return tables_out
    except ImportError:
        logger.warning(f"Tabula dependency není dostupná, přeskakuji PDF table fallback path={path}")
        return []


def _extract_tables_with_method(path: str, method: str, max_pages: int | None = None) -> list[list[list[str]]]:
    if method == "pdfplumber":
        return _extract_tables_pdfplumber_only(path, max_pages=max_pages)
    if method == "camelot":
        return _extract_tables_camelot(path)
    if method == "tabula":
        return _extract_tables_tabula(path)
    raise ValueError(f"Neznámá metoda extrakce tabulek: {method}")


def _extract_tables_with_fallback(path: str, force_method: str | None = None, max_pages: int | None = None) -> list[list[list[str]]]:
    global _LAST_TABLE_EXTRACTION_METHOD, _LAST_TABLE_PAGES
    _LAST_TABLE_EXTRACTION_METHOD = None
    _LAST_TABLE_PAGES = []
    if force_method is None:
        return _extract_tables_pdfplumber(path, max_pages=max_pages)

    methods = [force_method] if force_method else TABLE_METHOD_PREFERENCE
    for method in methods:
        tables = _extract_tables_with_method(path, method, max_pages=max_pages)
        if _has_min_table_rows(tables):
            _LAST_TABLE_EXTRACTION_METHOD = method
            if method != "pdfplumber":
                _LAST_TABLE_PAGES = [0] * len(tables)
            logger.info(f"table_extraction_method={method} path={path}")
            return tables
    logger.warning(f"table_extraction_method=none path={path}")
    return []


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
    parent_product_name: str | None = None,
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
        if _is_generic_product_name(product_name) and parent_product_name:
            product_name = parent_product_name
            EXTRACTION_DEBUG["propagated_product_names"] += 1
        elif parent_product_name and i > 0 and not product_name.lower().startswith(parent_product_name.lower()):
            product_name = f"{parent_product_name} – {product_name}"
            EXTRACTION_DEBUG["grouped_table_rows"] += 1
        fee_type = first_cell if i > 0 else header
        if _is_generic_product_name(product_name):
            _debug_reject("generic_product")
            continue
        if _is_blacklisted_label(product_name) or _is_blacklisted_label(fee_type):
            _debug_reject("blacklisted_label")
            continue
        if _is_invalid_threshold_row(fee_type, value):
            _debug_reject("threshold_row")
            continue
        currency = _extract_currency(value)
        period = _extract_period(cell, fee_type, header_text, row_text)
        confidence = _confidence_score(product_name, fee_type, value, currency, period)
        if confidence < 0.70:
            _debug_reject("low_confidence")
            continue
        conditions = "; ".join(c for j, c in enumerate(cells) if j not in {0, i} and c and not _extract_value(c))
        if not product_name or not fee_type:
            _debug_reject("orphan")
            continue
        row = PricingRow(
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
        )
        row_dict = asdict(row)
        row_dict["amount"] = _amount_from_value(value)
        is_valid, reason = is_valid_pricing_row(row_dict)
        if not is_valid:
            _debug_reject(reason or "strict_validation")
            continue
        records.append(row)
    return records


def extract_pricing_rows_from_pdf(
    pdf_path: Path,
    metadata: dict | None = None,
    max_pages: int | None = None,
    table_method: str | None = None,
) -> list[PricingRow]:
    metadata = metadata or {}
    source_url = metadata.get("url") or metadata.get("final_url") or f"file://{pdf_path}"
    title = metadata.get("title") or pdf_path.stem
    rows_out: list[PricingRow] = []
    try:
        tables = _extract_tables_with_fallback(str(pdf_path), force_method=table_method, max_pages=max_pages)
        metadata["table_extraction_method"] = _LAST_TABLE_EXTRACTION_METHOD
        table_pages = _LAST_TABLE_PAGES or [0] * len(tables)
        for table_index, cleaned_rows in enumerate(tables):
            if len(cleaned_rows) < TABLE_MIN_ROWS:
                continue
            width = max(len(row) for row in cleaned_rows)
            normalized = [row + [""] * (width - len(row)) for row in cleaned_rows]
            headers = _normalize_headers(normalized[0], width)
            body = normalized[1:]
            if not _is_pricing_table(headers, body):
                continue
            parent_product_name: str | None = None
            for row_index, cells in enumerate(body, start=1):
                header_candidate = _looks_like_product_header(cells)
                if header_candidate:
                    parent_product_name = header_candidate
                    EXTRACTION_DEBUG["grouped_table_rows"] += 1
                    continue
                rows_out.extend(_row_to_pricing_records(
                    headers, cells,
                    source_url=source_url,
                    source_file=pdf_path.name,
                    page=table_pages[table_index] if table_index < len(table_pages) else 0,
                    table_index=table_index,
                    row_index=row_index,
                    title=title,
                    parent_product_name=parent_product_name,
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


def write_rejected_rows_audit(stats: PricingQualityStats, output_path: Path | None = None) -> Path | None:
    output = output_path or (config.DISCOVERY_DIR / "pricing_rejected_rows.jsonl")
    rejected = list(stats.rejected_rows)
    if not rejected:
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rejected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info(f"Pricing rejected rows audit: {output} ({len(rejected)} rows)")
    return output


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
    table_method: str | None = None,
) -> dict:
    _reset_extraction_debug()
    metadata_by_file = load_document_metadata(pdf_dir)
    all_rows: list[PricingRow] = []
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    scanned = 0
    for pdf_path in pdfs:
        metadata = metadata_by_file.get(pdf_path.name, {})
        if not _is_likely_pricing_pdf(pdf_path, metadata):
            continue
        metadata_source_url = metadata.get("url") or ""
        if is_blacklisted_section(metadata_source_url):
            logger.info(f"Přeskočen blacklisted dokument: {pdf_path.name} ({metadata_source_url})")
            continue
        scanned += 1
        all_rows.extend(extract_pricing_rows_from_pdf(pdf_path, metadata, max_pages=max_pages_per_pdf, table_method=table_method))

    # ── Quality filter: remove garbage, header artifacts, blacklisted rows ──
    pre_filter_count = len(all_rows)
    all_rows, quality_stats = filter_pricing_dataclass_rows(all_rows)
    # Also remove blacklisted service rows (správa služby, tel. bankovnictví, etc.)
    all_rows_filtered: list[PricingRow] = []
    for row in all_rows:
        if is_pricing_blacklisted_row(asdict(row)):
            quality_stats.filtered_other += 1
        else:
            all_rows_filtered.append(row)
    all_rows = all_rows_filtered
    rejected_audit_path = write_rejected_rows_audit(quality_stats)

    write_pricing_rows(all_rows, output_path)
    stats = {
        "pdfs_total": len(pdfs),
        "pdfs_scanned": scanned,
        "rows": len(all_rows),
        "rows_before_quality_filter": pre_filter_count,
        "rows_filtered": pre_filter_count - len(all_rows),
        "output_path": str(output_path),
        "quality": quality_stats.to_dict(),
        "pricing_extraction_debug": {
            **EXTRACTION_DEBUG,
            "rejected_rows_count": EXTRACTION_DEBUG["rejected_rows_count"] + quality_stats.total_filtered,
            "quality_rejected_rows_count": quality_stats.total_filtered,
            "rejected_rows_audit_path": str(rejected_audit_path) if rejected_audit_path else "",
        },
        "top_products": Counter(r.product_name for r in all_rows).most_common(10),
        "top_fee_types": Counter(r.fee_type for r in all_rows).most_common(10),
    }
    logger.info(f"Structured pricing rows: {stats}")
    logger.info(f"Pricing quality filter: {quality_stats.summary()}")
    return stats

"""Enterprise structured loaders and semantic chunking for rb.cz RAG."""

from __future__ import annotations

import hashlib
import gc
import json
import pickle
import re
import resource
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from src.ingestion.parser import parse_pdf
from src.utils.logger import get_logger

logger = get_logger(__name__)

STRUCTURED_DIR = config.DATA_DIR / "crawl" / "structured"
DOCUMENTS_DIR = config.DATA_DIR / "documents"
MANIFEST_PATH = config.DATA_DIR / "ingestion_manifest.json"
MAX_EMBED_CHARS = 4000
MAX_EMBED_TOKENS_APPROX = 1500


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1024 if usage < 10**9 else usage / (1024 * 1024)


def _log_memory(stage: str) -> None:
    logger.info(f"Memory RSS stage={stage}: {_rss_mb():.1f} MB")

PRICING_TERMS = (
    "sazebník", "sazebnik", "ceník", "cenik", "fee", "price", "poplatek", "poplatky",
    "kč", "czk", "zdarma", "měsíčně", "mesicne", "ročně", "rocne", "sazba", "rpsn",
)

CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "corporate": ("firmy", "firma", "podnikatele", "podnikatel", "corporate", "firemní", "firemni", "podnikatelský", "podnikatelsky", "corp"),
    "retail": ("osobni", "osobní", "aktivní účet", "aktivni ucet", "ekonto", "běžný účet", "bezny ucet", "chytrý účet", "chytry ucet"),
    "accounts": ("ucet", "účet", "ucty", "účty", "ekonto"),
    "cards": ("karta", "karty", "kreditni", "kreditní", "debetni", "debetní"),
    "mortgages": ("hypoteka", "hypotéka", "hypotec"),
    "loans": ("pujcka", "půjčka", "uver", "úvěr", "rpsn"),
    "savings": ("sporeni", "spoření", "vklad"),
    "investments": ("invest", "fond", "dip"),
    "insurance": ("pojist", "pojišt"),
    "pricing": ("cenik", "ceník", "sazebnik", "sazebník", "poplat"),
    "documents": ("podmink", "podmínk", "dokument", "formular", "formulář"),
}

CORPORATE_TERMS = CATEGORY_RULES["corporate"]
RETAIL_TERMS = CATEGORY_RULES["retail"]
ARCHIVED_TERMS = (
    "již nenabízené", "jiz nenabizene", "discontinued", "archived", "archive",
    "staré produkty", "stare produkty", "nenabízené produkty", "nenabizene produkty",
    "již nenabízených", "jiz nenabizenych",
)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _hash(text: str) -> str:
    return hashlib.sha256(_clean(text).encode("utf-8")).hexdigest()


def _structured_sections(page: dict, title: str, path: Path) -> list[dict]:
    sections = page.get("sections") or []
    if sections:
        return sections

    content = _clean(page.get("content", ""))
    if not content:
        return []

    logger.info(
        "synthetic_section_created=true path=%s title=%s content_length=%s",
        path,
        title,
        len(content),
    )
    return [{"heading": title, "title": title, "content": content, "synthetic": True, "order": 0}]


def pricing_detected(*parts: str) -> bool:
    hay = " ".join(parts).lower()
    return any(term in hay for term in PRICING_TERMS)


def classify_category(*parts: str, fallback: str = "unknown") -> str:
    hay = " ".join(parts).lower()
    for category, needles in CATEGORY_RULES.items():
        if any(n in hay for n in needles):
            return category
    return fallback


def classify_business_category(*parts: str, fallback: str = "unknown") -> str:
    """High-priority retail/corporate/product category classifier for metadata."""
    hay = " ".join(parts).lower()
    if any(term in hay for term in CORPORATE_TERMS):
        return "corporate"
    if any(term in hay for term in RETAIL_TERMS):
        return "retail"
    if any(term in hay for term in CATEGORY_RULES["cards"]):
        return "cards"
    if any(term in hay for term in CATEGORY_RULES["mortgages"]):
        return "mortgages"
    if any(term in hay for term in CATEGORY_RULES["investments"]):
        return "investing"
    if any(term in hay for term in CATEGORY_RULES["insurance"]):
        return "insurance"
    return classify_category(*parts, fallback=fallback)


def classify_pricing_type(*parts: str) -> str:
    hay = " ".join(parts).lower()
    if any(term in hay for term in ("vedení účtu", "vedeni uctu", "měsíční poplatek", "mesicni poplatek", "běžný účet", "bezny ucet", "aktivní účet", "aktivni ucet", "ekonto")):
        return "account_fee"
    if any(term in hay for term in ("výběr", "vyber", "bankomat", "zahraničí", "zahranici", "atm")):
        return "withdrawal_fee"
    if any(term in hay for term in ("karta", "karty", "kreditní", "kreditni", "debetní", "debetni")):
        return "card_fee"
    if any(term in hay for term in ("hypot", "odhad", "zástav", "zastav", "úvěr na bydlení", "uver na bydleni")):
        return "mortgage_fee"
    return "generic_pricing"


def _is_pricing_table_text(*parts: str) -> bool:
    hay = " ".join(parts).lower()
    return any(term in hay for term in PRICING_TERMS + ("vedení účtu", "vedeni uctu", "produkt", "účet", "ucet", "tarif"))


def _is_bad_table_row(text: str) -> bool:
    from src.retrieval.query_classifier import detect_chunk_quality
    if detect_chunk_quality(text) in ("bad_pdf_extraction", "navigation_boilerplate"):
        return True
    tokens = re.findall(r"\S+", text[:1200])
    if len(tokens) < 6:
        return False
    single_ratio = sum(1 for token in tokens if len(token.strip(".,;:()[]{}|")) == 1) / len(tokens)
    return single_ratio > 0.28


def _extract_row_pricing_metadata(headers: list[str], values: list[str]) -> dict:
    pairs = [(h.strip(), v.strip()) for h, v in zip(headers, values) if h.strip() or v.strip()]
    product_name = ""
    fee_type = ""
    fee_value = ""

    for header, value in pairs:
        h = header.lower()
        v = value.strip()
        if not product_name and any(k in h for k in ("produkt", "účet", "ucet", "program", "tarif", "název", "nazev")):
            product_name = v
        if not fee_type and any(k in h for k in ("vedení", "vedeni", "poplatek", "cena", "frekvence", "výběr", "vyber")):
            fee_type = header
        if not fee_value and ("kč" in v.lower() or "zdarma" in v.lower() or re.search(r"\b\d+[,.]?\d*\s*(kč|czk|%)", v.lower())):
            fee_value = v

    if not product_name and values:
        product_name = values[0].strip()
    if not fee_type:
        for header, value in pairs:
            if "kč" in value.lower() or "zdarma" in value.lower():
                fee_type = header
                break
    return {"product_name": product_name, "fee_type": fee_type, "fee_value": fee_value}


def _row_chunk_text(table_title: str, section_title: str, source_url: str, page: int | None, headers: list[str], values: list[str]) -> str:
    lines = [
        f"Table: {table_title or section_title}",
        f"Sekce: {section_title}",
        f"Zdroj: {source_url}",
    ]
    if page:
        lines.append(f"Strana: {page}")
    lines.append("")
    for header, value in zip(headers, values):
        if header.strip() or value.strip():
            lines.append(f"{header.strip() or 'Sloupec'}: {value.strip()}")
    joined = " ".join(values).lower()
    if "ekonto" in joined:
        lines.append("Search aliases: eKonto ekonto ekonta vedení účtu vedeni uctu poplatek cena")
    return _clean("\n".join(lines))


def _parse_markdown_table_rows(markdown: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in markdown.splitlines() if "|" in line and line.strip()]
    if len(lines) < 3:
        return [], []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        if re.fullmatch(r"[:\-\s|]+", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(cells[: len(header)])
    return header, rows


def _make_pricing_row_docs(
    headers: list[str],
    rows: list[list[str]],
    base_metadata: dict,
    table_title: str,
    start_index: int,
) -> list[Document]:
    docs: list[Document] = []
    source_url = base_metadata.get("source_url", base_metadata.get("url", ""))
    section_title = base_metadata.get("section_title", base_metadata.get("title", ""))
    page = base_metadata.get("page")
    if not headers or not rows or not _is_pricing_table_text(" ".join(headers), table_title, section_title):
        return docs
    for offset, row in enumerate(rows):
        row_text_raw = " ".join(row)
        if not _is_pricing_table_text(row_text_raw, " ".join(headers), table_title, section_title):
            continue
        content = _row_chunk_text(table_title, section_title, source_url, page, headers, row)
        row_meta = {
            **base_metadata,
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "pricing_detected": True,
            "table_title": table_title,
            "table_headers": headers,
            "chunk_quality": "bad_table_row" if _is_bad_table_row(content) else "ok",
            **_extract_row_pricing_metadata(headers, row),
        }
        row_meta["pricing_type"] = classify_pricing_type(row_meta.get("fee_type", ""), row_meta.get("fee_value", ""), row_meta.get("product_name", ""), content)
        docs.append(_make_doc(content, row_meta, start_index + offset))
    return docs


def extract_document_date(*parts: str) -> str:
    """Extract best-effort document date as ISO yyyy-mm-dd from URL/title/text."""
    hay = " ".join(parts)
    # Common Czech numeric dates: 01.04.2018 / 1. 4. 2018
    m = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(20\d{2}|19\d{2})\b", hay)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}"
    # Filenames often contain ddmmyyyy, e.g. 01042018.
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2}|19\d{2})(?!\d)", hay)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}"
    # ISO-ish dates.
    m = re.search(r"\b(20\d{2}|19\d{2})[-_/](\d{2})[-_/](\d{2})\b", hay)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def extract_document_year(*parts: str) -> int | None:
    date = extract_document_date(*parts)
    if date:
        return int(date[:4])
    years = [int(y) for y in re.findall(r"\b(20\d{2}|19\d{2})\b", " ".join(parts))]
    return max(years) if years else None


def is_archived_document(*parts: str) -> bool:
    hay = " ".join(parts).lower()
    return any(term in hay for term in ARCHIVED_TERMS)


def classify_document_type(*parts: str, fallback: str = "document") -> str:
    hay = " ".join(parts).lower()
    if pricing_detected(hay):
        return "pricing"
    if "podmín" in hay or "podmink" in hay or "vop" in hay:
        return "terms"
    if "faq" in hay or "časté dotazy" in hay or "caste-dotazy" in hay:
        return "faq"
    return fallback


def _chunk_id(source_url: str, page: int | None, chunk_type: str, section_title: str, index: int, content: str) -> str:
    raw = f"{source_url}|{page}|{chunk_type}|{section_title}|{index}|{_hash(content)[:16]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _base_metadata(source_url: str, title: str, section_title: str, source_type: str, document_type: str, page: int | None, category: str, chunk_type: str, source_path: Path | None = None) -> dict:
    return {
        "source_url": source_url,
        "url": source_url,
        "source": str(source_path) if source_path else source_url,
        "title": title or section_title or source_url,
        "section_title": section_title or title or source_url,
        "source_type": source_type,
        "document_type": document_type,
        "page": page,
        "category": category,
        "chunk_type": chunk_type,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunk_size = min(chunk_size, MAX_EMBED_CHARS)
    overlap = min(overlap, max(0, chunk_size // 3))
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)


def _approx_tokens(text: str) -> int:
    # Conservative Czech-safe approximation for nomic-embed-text context guard.
    return max(len(text) // 3, len(text.split()))


def _within_embed_limit(text: str) -> bool:
    return len(text) <= MAX_EMBED_CHARS and _approx_tokens(text) <= MAX_EMBED_TOKENS_APPROX


def _split_plain_for_embed(text: str) -> list[str]:
    if _within_embed_limit(text):
        return [text]
    safe_size = min(MAX_EMBED_CHARS, MAX_EMBED_TOKENS_APPROX * 3, 3500)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=safe_size,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", "; ", " ", ""],
        length_function=len,
    )
    parts = splitter.split_text(text)
    # Last resort for pathological long tokens/no separators.
    final: list[str] = []
    for part in parts:
        if _within_embed_limit(part):
            final.append(part)
        else:
            for start in range(0, len(part), safe_size):
                final.append(part[start : start + safe_size])
    return [p for p in final if p.strip()]


def _split_table_for_embed(markdown: str) -> list[str]:
    """Split long markdown tables by rows while repeating the header."""
    markdown = _clean(markdown)
    if _within_embed_limit(markdown):
        return [markdown]

    lines = [line for line in markdown.splitlines() if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    non_table_lines = [line for line in lines if "|" not in line]
    if len(table_lines) < 3:
        return _split_plain_for_embed(markdown)

    header = table_lines[0]
    separator = table_lines[1] if re.search(r"\|?\s*:?-{3,}", table_lines[1]) else " | ".join(["---"] * max(1, header.count("|") + 1))
    rows = table_lines[2:]
    prefix = "\n".join(non_table_lines).strip()
    chunks: list[str] = []
    current_rows: list[str] = []

    def emit() -> None:
        if not current_rows:
            return
        body = "\n".join([header, separator, *current_rows])
        chunks.append(_clean(f"{prefix}\n\n{body}" if prefix else body))

    for row in rows:
        candidate_rows = [*current_rows, row]
        candidate_body = "\n".join([header, separator, *candidate_rows])
        candidate = _clean(f"{prefix}\n\n{candidate_body}" if prefix else candidate_body)
        if current_rows and not _within_embed_limit(candidate):
            emit()
            current_rows = [row]
        else:
            current_rows = candidate_rows
        if current_rows and not _within_embed_limit("\n".join([header, separator, *current_rows])):
            # Single row is still too long; split row text as fallback but keep header.
            long_row = current_rows.pop()
            emit()
            for part in _split_plain_for_embed(long_row):
                chunks.append(_clean("\n".join([header, separator, part])))
            current_rows = []
    emit()
    return [c for c in chunks if c.strip()]


def _make_doc(content: str, metadata: dict, index: int) -> Document:
    content = _clean(content)
    source_url = metadata.get("source_url", metadata.get("source", "unknown"))
    cid = _chunk_id(source_url, metadata.get("page"), metadata.get("chunk_type", "chunk"), metadata.get("section_title", ""), index, content)
    price = pricing_detected(content, metadata.get("title", ""), metadata.get("section_title", ""), source_url)
    doc_type = "pricing" if price else metadata.get("document_type", "document")
    chunk_type = "pricing" if price and metadata.get("chunk_type") in {"section_text", "pdf_text", "table", "pdf_table"} else metadata.get("chunk_type", "section_text")
    category = classify_business_category(
        source_url,
        metadata.get("source", ""),
        metadata.get("title", ""),
        metadata.get("section_title", ""),
        content[:1500],
        fallback=metadata.get("category", "unknown"),
    )
    pricing_type = classify_pricing_type(source_url, metadata.get("title", ""), metadata.get("section_title", ""), content[:1500]) if price or doc_type == "pricing" else ""
    from src.retrieval.query_classifier import detect_chunk_quality
    chunk_quality = metadata.get("chunk_quality") or detect_chunk_quality(content)
    document_date = extract_document_date(source_url, metadata.get("source", ""), metadata.get("title", ""), metadata.get("section_title", ""), content[:1500])
    document_year = extract_document_year(source_url, metadata.get("source", ""), metadata.get("title", ""), metadata.get("section_title", ""), content[:1500])
    archived = is_archived_document(source_url, metadata.get("source", ""), metadata.get("title", ""), metadata.get("section_title", ""), content[:1500])
    enriched = {
        **metadata,
        "document_type": doc_type,
        "chunk_type": chunk_type,
        "category": category,
        "pricing_type": pricing_type,
        "chunk_quality": chunk_quality,
        "document_date": document_date,
        "document_year": document_year,
        "is_archived": archived,
        "is_discontinued": archived,
        "pricing_detected": price,
        "content_hash": _hash(content),
        "chunk_id": cid,
        "chunk_index": index,
        "char_count": len(content),
        "file_name": Path(str(metadata.get("source", source_url))).name,
    }
    return Document(page_content=content, metadata=enriched)


def _enforce_embed_limits(chunks: list[Document]) -> list[Document]:
    before = len(chunks)
    output: list[Document] = []
    split_count = 0
    longest_before = max((len(c.page_content) for c in chunks), default=0)

    for doc in chunks:
        if _within_embed_limit(doc.page_content):
            output.append(doc)
            continue

        split_count += 1
        parent_id = doc.metadata.get("chunk_id") or _hash(doc.page_content)[:16]
        chunk_type = doc.metadata.get("chunk_type", "")
        if chunk_type in {"table", "pdf_table", "pricing"} and "|" in doc.page_content:
            parts = _split_table_for_embed(doc.page_content)
        else:
            parts = _split_plain_for_embed(doc.page_content)

        for sub_idx, part in enumerate(parts):
            md = {
                **doc.metadata,
                "parent_chunk_id": parent_id,
                "subchunk_index": sub_idx,
                "char_count": len(part),
                "content_hash": _hash(part),
            }
            md["chunk_id"] = _chunk_id(
                md.get("source_url", md.get("source", "unknown")),
                md.get("page"),
                md.get("chunk_type", "chunk"),
                md.get("section_title", ""),
                sub_idx,
                f"{parent_id}|{part}",
            )
            output.append(Document(page_content=part, metadata=md))

    longest_after = max((len(c.page_content) for c in output), default=0)
    logger.info(
        "Embed-limit split: "
        f"před={before}, po={len(output)}, nejdelší před={longest_before}, "
        f"nejdelší po={longest_after}, splitnuto={split_count}"
    )
    return output


def load_structured_pages(structured_dir: Path = STRUCTURED_DIR, chunk_size: int = 1100, overlap: int = 150) -> list[Document]:
    docs: list[Document] = []
    MAX_STRUCTURED_BYTES = 5 * 1024 * 1024  # 5 MB — skip media exports, PPTX
    skipped_large = 0
    for path in sorted(structured_dir.glob("*.json")):
        if path.stat().st_size > MAX_STRUCTURED_BYTES:
            skipped_large += 1
            continue
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Structured JSON nelze číst {path}: {exc}")
            continue
        url = page.get("url", "")
        title = page.get("title", "") or url
        meta = page.get("metadata", {}) or {}
        category = classify_business_category(url, title, fallback=meta.get("category") or "unknown")
        document_type = meta.get("document_type") or classify_document_type(url, title, fallback="product_page")
        sections = _structured_sections(page, title, path)

        idx = 0
        for section in sections:
            section_title = section.get("heading") or title
            for part in _split_text(section.get("content", ""), chunk_size, overlap):
                docs.append(_make_doc(part, _base_metadata(url, title, section_title, "web", document_type, None, category, "section_text", path), idx))
                idx += 1
        for item in page.get("faq", []):
            content = f"FAQ: {item.get('question', '')}\n\nOdpověď:\n{item.get('answer', '')}"
            if len(_clean(content)) > 30:
                md = _base_metadata(url, title, item.get("section_title") or title, "web", "faq", None, category, "faq", path)
                md["faq_question"] = item.get("question", "")
                docs.append(_make_doc(content, md, idx)); idx += 1
        for table in page.get("tables", []):
            content = table.get("markdown", "")
            if len(_clean(content)) > 20:
                md = _base_metadata(url, title, table.get("section_title") or table.get("caption") or title, "web", document_type, None, category, "table", path)
                md["table_caption"] = table.get("caption", "")
                headers, rows = _parse_markdown_table_rows(content)
                row_docs = _make_pricing_row_docs(headers, rows, md, table.get("caption") or md.get("section_title") or title, idx)
                docs.extend(row_docs)
                idx += len(row_docs)
                docs.append(_make_doc(content, md, idx)); idx += 1
        for card in page.get("cards", []):
            content = card.get("content", "")
            if len(_clean(content)) > 50:
                docs.append(_make_doc(content, _base_metadata(url, title, card.get("title") or title, "web", document_type, None, category, "section_text", path), idx)); idx += 1
    if skipped_large:
        logger.info(f"Skipped {skipped_large} large structured JSONs (>5 MB)")
    logger.info(f"Structured pages → {len(docs)} semantic chunků")
    return docs


def load_markdown_exports(structured_dir: Path = STRUCTURED_DIR, chunk_size: int = 1100, overlap: int = 150) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(structured_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if len(raw.strip()) < 80:
            continue
        title = raw.splitlines()[0].lstrip("# ").strip() if raw.splitlines() else path.stem
        source_match = re.search(r"Zdroj:\s*(https?://\S+)", raw)
        url = source_match.group(1) if source_match else str(path)
        category = classify_business_category(url, title)
        doc_type = classify_document_type(url, title, raw, fallback="markdown")
        for idx, part in enumerate(_split_text(raw, chunk_size, overlap)):
            docs.append(_make_doc(part, _base_metadata(url, title, title, "markdown", doc_type, None, category, "section_text", path), idx))
    logger.info(f"Markdown exports → {len(docs)} chunků")
    return docs


def load_pdf_documents(pdf_dir: Path = DOCUMENTS_DIR, chunk_size: int = 1100, overlap: int = 150) -> list[Document]:
    docs: list[Document] = []
    metadata_by_file = {}
    metadata_path = pdf_dir / "metadata.jsonl"
    if metadata_path.exists():
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                metadata_by_file[row.get("filename", "")] = row
            except Exception:
                pass
    MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB — skip annual reports, magazines
    skipped_large = 0
    skipped_non_pdf = 0
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        if pdf_path.suffix.lower() != ".pdf":
            skipped_non_pdf += 1
            continue
        if pdf_path.stat().st_size > MAX_PDF_BYTES:
            skipped_large += 1
            logger.info(f"Skipping large PDF ({pdf_path.stat().st_size / 1024 / 1024:.0f} MB): {pdf_path.name}")
            continue
        row = metadata_by_file.get(pdf_path.name, {})
        title = row.get("title") or pdf_path.stem
        source_url = row.get("url") or row.get("final_url") or f"file://{pdf_path}"
        category = classify_business_category(source_url, title, pdf_path.name, fallback=row.get("category") or "unknown")
        doc_type = classify_document_type(source_url, title, pdf_path.name, fallback="document")
        for page_doc in parse_pdf(pdf_path):
            page_num = page_doc.metadata.get("page")
            chunk_type = "pdf_table" if page_doc.metadata.get("has_tables") else "pdf_text"
            section_title = title
            for idx, part in enumerate(_split_text(page_doc.page_content, chunk_size, overlap)):
                md = _base_metadata(source_url, title, section_title, "pdf", doc_type, page_num, category, chunk_type, pdf_path)
                md.update({"total_pages": page_doc.metadata.get("total_pages"), "has_tables": page_doc.metadata.get("has_tables"), "table_count": page_doc.metadata.get("table_count", 0)})
                # PDF pricing rows are now extracted only from true table cells by
                # src.ingestion.pricing_extractor into data/pricing/pricing_rows.jsonl.
                # Do not create pricing_row chunks from markdown/raw OCR-like PDF text.
                docs.append(_make_doc(part, md, idx))
    if skipped_large:
        logger.info(f"Skipped {skipped_large} large PDFs (>20 MB)")
    if skipped_non_pdf:
        logger.info(f"Skipped {skipped_non_pdf} non-PDF files")
    logger.info(f"PDF documents → {len(docs)} chunků")
    return docs


def _iter_structured_documents(structured_dir: Path = STRUCTURED_DIR, chunk_size: int = 1100, overlap: int = 150):
    MAX_STRUCTURED_BYTES = 5 * 1024 * 1024
    for path in sorted(structured_dir.glob("*.json")):
        if path.stat().st_size > MAX_STRUCTURED_BYTES:
            continue
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Structured JSON nelze číst {path}: {exc}")
            continue
        url = page.get("url", "")
        title = page.get("title", "") or url
        meta = page.get("metadata", {}) or {}
        category = classify_business_category(url, title, fallback=meta.get("category") or "unknown")
        document_type = meta.get("document_type") or classify_document_type(url, title, fallback="product_page")
        sections = _structured_sections(page, title, path)
        idx = 0
        for section in sections:
            section_title = section.get("heading") or title
            for part in _split_text(section.get("content", ""), chunk_size, overlap):
                yield _make_doc(part, _base_metadata(url, title, section_title, "web", document_type, None, category, "section_text", path), idx)
                idx += 1
        for item in page.get("faq", []):
            content = f"FAQ: {item.get('question', '')}\n\nOdpověď:\n{item.get('answer', '')}"
            if len(_clean(content)) > 30:
                md = _base_metadata(url, title, item.get("section_title") or title, "web", "faq", None, category, "faq", path)
                md["faq_question"] = item.get("question", "")
                yield _make_doc(content, md, idx); idx += 1
        for table in page.get("tables", []):
            content = table.get("markdown", "")
            if len(_clean(content)) > 20:
                md = _base_metadata(url, title, table.get("section_title") or table.get("caption") or title, "web", document_type, None, category, "table", path)
                md["table_caption"] = table.get("caption", "")
                headers, rows = _parse_markdown_table_rows(content)
                for row_doc in _make_pricing_row_docs(headers, rows, md, table.get("caption") or md.get("section_title") or title, idx):
                    yield row_doc
                    idx += 1
                yield _make_doc(content, md, idx); idx += 1
        for card in page.get("cards", []):
            content = card.get("content", "")
            if len(_clean(content)) > 50:
                yield _make_doc(content, _base_metadata(url, title, card.get("title") or title, "web", document_type, None, category, "section_text", path), idx)
                idx += 1
        del page


def _iter_pdf_documents(pdf_dir: Path = DOCUMENTS_DIR, chunk_size: int = 1100, overlap: int = 150):
    metadata_by_file = {}
    metadata_path = pdf_dir / "metadata.jsonl"
    if metadata_path.exists():
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                metadata_by_file[row.get("filename", "")] = row
            except Exception:
                pass
    MAX_PDF_BYTES = 20 * 1024 * 1024
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        if pdf_path.stat().st_size > MAX_PDF_BYTES:
            continue
        row = metadata_by_file.get(pdf_path.name, {})
        title = row.get("title") or pdf_path.stem
        source_url = row.get("url") or row.get("final_url") or f"file://{pdf_path}"
        category = classify_business_category(source_url, title, pdf_path.name, fallback=row.get("category") or "unknown")
        doc_type = classify_document_type(source_url, title, pdf_path.name, fallback="document")
        for page_doc in parse_pdf(pdf_path):
            page_num = page_doc.metadata.get("page")
            chunk_type = "pdf_table" if page_doc.metadata.get("has_tables") else "pdf_text"
            for idx, part in enumerate(_split_text(page_doc.page_content, chunk_size, overlap)):
                md = _base_metadata(source_url, title, title, "pdf", doc_type, page_num, category, chunk_type, pdf_path)
                md.update({"total_pages": page_doc.metadata.get("total_pages"), "has_tables": page_doc.metadata.get("has_tables"), "table_count": page_doc.metadata.get("table_count", 0)})
                yield _make_doc(part, md, idx)


def iter_enterprise_chunk_batches(
    include_structured: bool = True,
    include_markdown: bool = False,
    include_pdfs: bool = True,
    structured_dir: Path = STRUCTURED_DIR,
    pdf_dir: Path = DOCUMENTS_DIR,
    chunk_size: int = 1100,
    overlap: int = 150,
    batch_size: int = 256,
):
    """Yield deduplicated enterprise chunks in bounded memory batches."""
    seen: set[str] = set()
    batch: list[Document] = []
    total = 0

    def emit_if_ready(force: bool = False):
        nonlocal batch, total
        if batch and (force or len(batch) >= batch_size):
            limited = _enforce_embed_limits(batch)
            total += len(limited)
            logger.info(f"Memory-safe enterprise batch emit: size={len(limited)}, total_emitted={total}")
            _log_memory("enterprise_batch_emit")
            out = limited
            batch = []
            gc.collect()
            return out
        return None

    sources = []
    if include_structured:
        sources.append(_iter_structured_documents(structured_dir, chunk_size, overlap))
    if include_markdown:
        # Markdown is usually fallback-only; keep existing loader for compatibility, but batch it.
        sources.append(iter(load_markdown_exports(structured_dir, chunk_size, overlap)))
    if include_pdfs:
        sources.append(_iter_pdf_documents(pdf_dir, chunk_size, overlap))

    for source in sources:
        for doc in source:
            cid = doc.metadata.get("chunk_id")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            batch.append(doc)
            emitted = emit_if_ready(False)
            if emitted is not None:
                yield emitted
        gc.collect()
    emitted = emit_if_ready(True)
    if emitted is not None:
        yield emitted
    logger.info(f"Memory-safe enterprise chunks emitted total={total}, dedupe_seen={len(seen)}")


def build_enterprise_chunks(
    include_structured: bool = True,
    include_markdown: bool = False,
    include_pdfs: bool = True,
    structured_dir: Path = STRUCTURED_DIR,
    pdf_dir: Path = DOCUMENTS_DIR,
    chunk_size: int = 1100,
    overlap: int = 150,
) -> list[Document]:
    chunks: list[Document] = []
    if include_structured:
        chunks.extend(load_structured_pages(structured_dir, chunk_size, overlap))
    if include_markdown:
        chunks.extend(load_markdown_exports(structured_dir, chunk_size, overlap))
    if include_pdfs:
        chunks.extend(load_pdf_documents(pdf_dir, chunk_size, overlap))
    seen: set[str] = set()
    deduped: list[Document] = []
    for doc in chunks:
        cid = doc.metadata.get("chunk_id")
        if cid in seen:
            continue
        seen.add(cid)
        deduped.append(doc)
    deduped = _enforce_embed_limits(deduped)
    write_manifest(deduped)
    logger.info(f"Enterprise chunks: {len(chunks)} → {len(deduped)} po deduplikaci")
    return deduped


def write_manifest(chunks: list[Document], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for doc in chunks:
        by_type[doc.metadata.get("chunk_type", "unknown")] = by_type.get(doc.metadata.get("chunk_type", "unknown"), 0) + 1
        by_source[doc.metadata.get("source_type", "unknown")] = by_source.get(doc.metadata.get("source_type", "unknown"), 0) + 1
        by_category[doc.metadata.get("category", "unknown")] = by_category.get(doc.metadata.get("category", "unknown"), 0) + 1
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chunk_count": len(chunks),
        "pricing_chunks": sum(1 for c in chunks if c.metadata.get("document_type") == "pricing" or c.metadata.get("pricing_detected")),
        "chunk_types": by_type,
        "source_types": by_source,
        "categories": by_category,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def enrich_existing_metadata(doc: Document) -> Document:
    """Recompute category/pricing_type metadata for an existing chunk."""
    md = dict(doc.metadata)
    source_url = str(md.get("source_url") or md.get("url") or md.get("source") or "")
    title = str(md.get("title") or md.get("file_name") or "")
    section_title = str(md.get("section_title") or "")
    content = doc.page_content[:2000]
    price = pricing_detected(source_url, title, section_title, content)
    md["category"] = classify_business_category(source_url, title, section_title, str(md.get("file_name", "")), content, fallback=md.get("category", "unknown"))
    if price or md.get("document_type") == "pricing":
        md["document_type"] = "pricing"
        md["pricing_detected"] = True
        md["pricing_type"] = classify_pricing_type(source_url, title, section_title, content)
    else:
        md.setdefault("pricing_type", "")
    from src.retrieval.query_classifier import detect_chunk_quality
    md["chunk_quality"] = detect_chunk_quality(doc.page_content)
    md["document_date"] = extract_document_date(source_url, title, section_title, str(md.get("file_name", "")), content)
    md["document_year"] = extract_document_year(source_url, title, section_title, str(md.get("file_name", "")), content)
    archived = is_archived_document(source_url, title, section_title, str(md.get("file_name", "")), content)
    md["is_archived"] = archived
    md["is_discontinued"] = archived
    return Document(page_content=doc.page_content, metadata=md)


def reclassify_metadata(docs_store_path: Path = config.DOCS_STORE_PATH, update_qdrant: bool = True) -> dict:
    """Reclassify metadata in BM25 docs store and Qdrant payloads without re-embedding."""
    if not docs_store_path.exists():
        return {"updated": 0, "error": f"Docs store neexistuje: {docs_store_path}"}

    with docs_store_path.open("rb") as f:
        docs: list[Document] = pickle.load(f)

    updated_docs = [enrich_existing_metadata(doc) for doc in docs]
    with docs_store_path.open("wb") as f:
        pickle.dump(updated_docs, f)

    qdrant_updated = 0
    if update_qdrant:
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
            for doc in updated_docs:
                cid = doc.metadata.get("chunk_id")
                if not cid:
                    continue
                point_id = int(cid, 16)
                payload = {
                    "category": doc.metadata.get("category"),
                    "pricing_type": doc.metadata.get("pricing_type"),
                    "document_type": doc.metadata.get("document_type"),
                    "pricing_detected": doc.metadata.get("pricing_detected"),
                }
                client.set_payload(collection_name=config.QDRANT_COLLECTION, payload=payload, points=[point_id])
                qdrant_updated += 1
        except Exception as exc:
            logger.warning(f"Qdrant payload reclassification selhala: {exc}")

    return {"updated": len(updated_docs), "qdrant_updated": qdrant_updated}

"""
Indexace chunků do Qdrant (dense) a BM25 (sparse).

Dva režimy indexace:

  INCREMENTAL (výchozí) – přidává pouze nové dokumenty
    1. Načte množinu chunk_id z existující Qdrant kolekce (scroll API)
    2. Vyfiltruje chunky jejichž chunk_id již existuje → přeskočí je
    3. Embedduje a indexuje pouze nové chunky
    4. Přidá nové chunky do BM25 pickle (zachová existující)

  FULL – kompletní reindexace od nuly
    1. Smaže a znovu vytvoří Qdrant kolekci
    2. Embedduje a indexuje všechny chunky
    3. Přepíše BM25 pickle

Deterministické point IDs:
  Každý chunk dostane Qdrant point ID odvozené z jeho chunk_id (hex → uint64).
  Stejný chunk_id → stejné point ID → Qdrant upsert je idempotentní i při
  vícenásobném spuštění bez explicitní deduplikace.
"""

from __future__ import annotations

import pickle
import gc
import hashlib
import json
import random
import re
import resource
import time
from collections import deque
from pathlib import Path

from langchain_core.documents import Document
from tqdm import tqdm

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

_UPSERT_BATCH_SIZE = 16
_SCROLL_BATCH_SIZE = 1000
MAX_EMBED_CHARS = 4000
MAX_EMBED_TOKENS_APPROX = 1500
_OPENAI_MAX_BATCH_TOKENS = 3500


def _rss_mb() -> float:
    """Best-effort resident set size in MB for memory-pressure logging."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KB, macOS bytes. This environment is Linux, keep fallback sane.
    return usage / 1024 if usage < 10**9 else usage / (1024 * 1024)


def log_memory(stage: str) -> None:
    logger.info(f"Memory RSS stage={stage}: {_rss_mb():.1f} MB")


# ---------------------------------------------------------------------------
# Klientské singletons
# ---------------------------------------------------------------------------

def _get_embeddings():
    if config.EMBEDDING_BACKEND == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("EMBEDDING_BACKEND=openai vyžaduje OPENAI_API_KEY")
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise RuntimeError("Chybí langchain-openai. Spusťte: pip install langchain-openai openai") from exc
        return OpenAIEmbeddings(
            model=config.OPENAI_EMBED_MODEL,
            api_key=config.OPENAI_API_KEY,
            request_timeout=config.OPENAI_EMBED_TIMEOUT_SECONDS,
        )

    if config.EMBEDDING_BACKEND != "ollama":
        raise RuntimeError("EMBEDDING_BACKEND musí být 'ollama' nebo 'openai'")
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(model=config.EMBED_MODEL, base_url=config.OLLAMA_BASE_URL)


def _get_qdrant_client():
    t_import = time.perf_counter()
    from qdrant_client import QdrantClient
    logger.info(f"import_timing.qdrant_client.QdrantClient ms={(time.perf_counter() - t_import) * 1000:.1f}")

    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT, timeout=config.QDRANT_TIMEOUT_SECONDS)


def _qmodels():
    from qdrant_client.http import models as qdrant_models

    return qdrant_models


# ---------------------------------------------------------------------------
# Point ID: chunk_id → deterministický uint64
# ---------------------------------------------------------------------------

def _chunk_id_to_point_id(chunk_id: str) -> int:
    """
    Převede hexadecimální chunk_id na uint64 pro Qdrant point ID.

    chunk_id je prvních 16 hex znaků SHA256 = 64 bitů, vždy se vejde do uint64.
    Deterministické mapování znamená:
      - Stejný chunk → stejné point ID napříč běhy
      - Qdrant upsert je bezpečně idempotentní
      - Existence chunku lze ověřit bez scrollování celé kolekce
    """
    return int(chunk_id, 16)


def _approx_tokens(text: str) -> int:
    return max(len(text) // 3, len(text.split()))


def _within_embed_limit(text: str) -> bool:
    return len(text) <= MAX_EMBED_CHARS and _approx_tokens(text) <= MAX_EMBED_TOKENS_APPROX


def _split_plain_fallback(text: str) -> list[str]:
    safe_size = min(MAX_EMBED_CHARS, MAX_EMBED_TOKENS_APPROX * 3, 3500)
    parts: list[str] = []
    paragraphs = re.split(r"(\n\n+)", text)
    current = ""
    for part in paragraphs:
        candidate = (current + part).strip()
        if current and not _within_embed_limit(candidate):
            parts.append(current.strip())
            current = part.strip()
        else:
            current = candidate
    if current.strip():
        parts.append(current.strip())
    final: list[str] = []
    for part in parts:
        if _within_embed_limit(part):
            final.append(part)
        else:
            for start in range(0, len(part), safe_size):
                final.append(part[start : start + safe_size])
    return [p for p in final if p.strip()]


def _split_table_fallback(markdown: str) -> list[str]:
    if _within_embed_limit(markdown):
        return [markdown]
    lines = [line for line in markdown.splitlines() if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) < 3:
        return _split_plain_fallback(markdown)
    header = table_lines[0]
    separator = table_lines[1]
    rows = table_lines[2:]
    chunks: list[str] = []
    current: list[str] = []
    for row in rows:
        candidate = "\n".join([header, separator, *current, row])
        if current and not _within_embed_limit(candidate):
            chunks.append("\n".join([header, separator, *current]))
            current = [row]
        else:
            current.append(row)
    if current:
        chunks.append("\n".join([header, separator, *current]))
    final: list[str] = []
    for chunk in chunks:
        if _within_embed_limit(chunk):
            final.append(chunk)
        else:
            for part in _split_plain_fallback(chunk):
                final.append("\n".join([header, separator, part]) if "|" not in part else part)
    return final


def _tokenize_bm25(text: str) -> list[str]:
    return [token for token in re.findall(r"[\wÀ-ɏ]+", text.lower()) if token]


def _bm25_searchable_text(chunk: Document) -> str:
    """Index visible content plus high-signal metadata for row-level pricing recall."""
    md = chunk.metadata
    extra_fields = []
    if md.get("chunk_type") == "pricing_row":
        extra_fields.extend([
            md.get("product_name", ""),
            md.get("fee_type", ""),
            md.get("fee_value", ""),
            md.get("pricing_type", ""),
            "pricing_row poplatek cena vedení účtu vedeni uctu",
        ])
        product = str(md.get("product_name") or "").lower()
        if "ekonto" in product or "ekonto" in chunk.page_content.lower():
            extra_fields.append("eKonto ekonto ekonta")
    return "\n".join([chunk.page_content, *(str(x) for x in extra_fields if x)])


def _pricing_doc_generation(row: dict) -> int:
    """Best-effort sortable generation/year for structured pricing rows."""
    for key in ("document_generation", "document_year", "source_year"):
        value = row.get(key)
        try:
            if value not in (None, ""):
                return int(value)
        except Exception:
            continue
    text = " ".join(str(row.get(k) or "") for k in ("valid_from", "source_date", "title", "source_file", "source_url"))
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", text)]
    return max(years) if years else 0


def _pricing_bm25_dedupe_key(row: dict) -> tuple[str, str, str, str]:
    """Canonical key that suppresses stale contradictory rows for one fee slot."""
    from src.retrieval.pricing_retriever import _norm

    groups = row.get("canonical_product_groups") or []
    canonical = "|".join(sorted(str(g) for g in groups if g)) or str(row.get("canonical_product") or row.get("product_name") or "")
    fee_type = str(row.get("fee_type") or row.get("pricing_type") or "")
    pricing_type = str(row.get("pricing_type") or "")
    period = str(row.get("period") or row.get("billing_period") or "")
    return (_norm(canonical), _norm(fee_type), _norm(pricing_type), _norm(period))


def _pricing_bm25_rank(row: dict) -> tuple[int, int, int, int, float]:
    """Prefer current official rows over older/generic rows during BM25 corpus cleanup."""
    hay = " ".join(str(row.get(k) or "") for k in ("source_file", "source_url", "title", "document_type"))
    hay_norm = hay.lower()
    official = int(("cenik" in hay_norm or "sazeb" in hay_norm or "pricing" in hay_norm) and ("pdf" in hay_norm or row.get("document_type") == "pricing"))
    table_row = int(row.get("table_index") is not None or row.get("row_index") is not None)
    confidence = row.get("confidence") or 0
    try:
        confidence_float = float(confidence)
    except Exception:
        confidence_float = 0.0
    return (
        1 if row.get("is_active") is True and row.get("is_archived") is not True else 0,
        _pricing_doc_generation(row),
        official,
        table_row,
        confidence_float,
    )


def _pricing_row_to_bm25_document(row: dict) -> Document:
    """Convert one normalized pricing JSONL row into a BM25-only Document."""
    from src.retrieval.pricing_resolver import normalize_row_price

    normalized = normalize_row_price(row)
    canonical_groups = row.get("canonical_product_groups") or []
    canonical_product = canonical_groups[0] if canonical_groups else row.get("canonical_product")
    generation = _pricing_doc_generation(row)
    content = (
        f"Produkt: {row.get('product_name', '')}\n"
        f"Typ poplatku: {row.get('fee_type', '')}\n"
        f"Cena: {row.get('fee_value') or row.get('amount') or ''}\n"
        f"Normalizovaná cena: {normalized.get('normalized_price')} {normalized.get('currency') or row.get('currency') or ''}\n"
        f"Období: {row.get('period') or normalized.get('billing_period') or ''}\n"
        f"Podmínky: {row.get('conditions') or row.get('condition_text') or ''}\n"
        f"Zdroj: {row.get('source_file') or row.get('source_url') or ''}\n"
        f"Rok dokumentu: {generation or ''}"
    ).strip()
    content_hash = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    metadata = {
        **row,
        "chunk_type": "pricing_row",
        "document_type": "pricing",
        "chunk_quality": "ok",
        "structured_pricing": True,
        "source_type": "structured_pricing_row",
        "canonical_product": canonical_product,
        "canonical_product_groups": canonical_groups,
        "fee_type": row.get("fee_type"),
        "normalized_price": normalized.get("normalized_price"),
        "currency": normalized.get("currency") or row.get("currency"),
        "billing_period": normalized.get("billing_period") or row.get("period"),
        "normalized_currency": normalized.get("currency") or row.get("currency"),
        "normalized_billing_period": normalized.get("billing_period") or row.get("period"),
        "pricing_semantic_label": normalized.get("semantic_label"),
        "source_file": row.get("source_file") or row.get("source_url") or "pricing_rows.jsonl",
        "document_generation": generation,
        "content_hash": content_hash,
        "chunk_id": f"pricing_row_jsonl:{content_hash[:24]}",
    }
    return Document(page_content=content, metadata=metadata)


def load_structured_pricing_bm25_docs() -> list[Document]:
    """Load active structured pricing rows and convert them into BM25 documents.

    This is BM25-only enrichment: it does not touch Qdrant, embeddings, crawling,
    or the source JSONL. Stale/inactive rows and contradictory older rows are
    suppressed before writing ``documents.pkl``.
    """
    from src.ingestion.quality_filters import is_valid_pricing_row
    from src.retrieval.pricing_retriever import _normalize_pricing_metadata, load_pricing_rows

    best: dict[tuple[str, str, str, str], dict] = {}
    total = 0
    invalid = 0
    inactive = 0
    for raw_row in load_pricing_rows():
        total += 1
        row = _normalize_pricing_metadata(raw_row)
        valid, _reason = is_valid_pricing_row(row)
        if not valid:
            invalid += 1
            continue
        if row.get("is_active") is not True or row.get("is_archived") is True:
            inactive += 1
            continue
        key = _pricing_bm25_dedupe_key(row)
        if not any(key):
            key = (hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(), "", "", "")
        current = best.get(key)
        if current is None or _pricing_bm25_rank(row) > _pricing_bm25_rank(current):
            best[key] = row

    docs = [_pricing_row_to_bm25_document(row) for row in best.values()]
    logger.info(
        "Structured pricing BM25 docs: loaded=%s invalid=%s inactive_or_archived=%s deduped=%s",
        total, invalid, inactive, len(docs),
    )
    return docs


def _replace_structured_pricing_bm25_docs(chunks: list[Document]) -> list[Document]:
    """Merge chunks with regenerated JSONL pricing rows for BM25 docs store."""
    base_chunks = [
        c for c in chunks
        if not (
            c.metadata.get("source_type") == "structured_pricing_row"
            or str(c.metadata.get("chunk_id") or "").startswith("pricing_row_jsonl:")
        )
    ]
    pricing_docs = load_structured_pricing_bm25_docs()
    existing_ids = {c.metadata.get("chunk_id") for c in base_chunks if c.metadata.get("chunk_id")}
    pricing_docs = [d for d in pricing_docs if d.metadata.get("chunk_id") not in existing_ids]
    return base_chunks + pricing_docs


def _guard_embed_chunks(chunks: list[Document]) -> list[Document]:
    before = len(chunks)
    longest = sorted(chunks, key=lambda c: len(c.page_content), reverse=True)[:5]
    if longest:
        logger.info(
            "Embed guard nejdelší chunky: "
            + "; ".join(
                f"{len(c.page_content)} chars/{_approx_tokens(c.page_content)} tok approx "
                f"id={c.metadata.get('chunk_id')} source={c.metadata.get('file_name', c.metadata.get('source'))}"
                for c in longest
            )
        )

    output: list[Document] = []
    split_count = 0
    for doc in chunks:
        if _within_embed_limit(doc.page_content):
            output.append(doc)
            continue
        split_count += 1
        parent_id = doc.metadata.get("chunk_id") or hashlib.sha256(doc.page_content.encode()).hexdigest()[:16]
        chunk_type = doc.metadata.get("chunk_type", "")
        parts = _split_table_fallback(doc.page_content) if chunk_type in {"table", "pdf_table", "pricing"} and "|" in doc.page_content else _split_plain_fallback(doc.page_content)
        for sub_idx, part in enumerate(parts):
            if not _within_embed_limit(part):
                logger.warning(
                    f"Přeskakuji oversized subchunk po fallback splitu: {len(part)} chars, "
                    f"{_approx_tokens(part)} tok approx, parent={parent_id}"
                )
                continue
            content_hash = hashlib.sha256(part.strip().encode()).hexdigest()
            raw_id = f"{parent_id}:sub:{sub_idx}:{content_hash[:16]}"
            metadata = {
                **doc.metadata,
                "parent_chunk_id": parent_id,
                "subchunk_index": sub_idx,
                "chunk_id": hashlib.sha256(raw_id.encode()).hexdigest()[:16],
                "content_hash": content_hash,
                "char_count": len(part),
            }
            output.append(Document(page_content=part, metadata=metadata))
    logger.info(
        f"Embed guard: počet chunků před splittem={before}, po splitu={len(output)}, "
        f"nejdelší chunk={max((len(c.page_content) for c in output), default=0)}, splitnuto={split_count}"
    )
    return output


def _progress_path() -> Path:
    safe_collection = re.sub(r"[^\w.-]+", "_", config.QDRANT_COLLECTION)
    return config.INDEX_DIR / f"embedding_progress_{safe_collection}_{config.EMBEDDING_BACKEND}.json"


def _load_progress() -> dict:
    path = _progress_path()
    if not path.exists():
        return {"last_successful_batch": -1, "completed_chunk_ids": [], "failed_chunk_ids": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Nelze načíst embedding progress {path}: {exc}")
        return {"last_successful_batch": -1, "completed_chunk_ids": [], "failed_chunk_ids": []}


def _save_progress(batch_index: int, chunk_ids: list[str], failed_chunk_ids: list[str] | None = None) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = _progress_path()
    payload = {
        "collection": config.QDRANT_COLLECTION,
        "embedding_backend": config.EMBEDDING_BACKEND,
        "embedding_model": config.get_active_embed_model(),
        "vector_size": config.QDRANT_VECTOR_SIZE,
        "last_successful_batch": batch_index,
        "completed_chunk_ids": chunk_ids,
        "failed_chunk_ids": failed_chunk_ids or [],
        "completed_count": len(chunk_ids),
        "failed_count": len(failed_chunk_ids or []),
        "updated_at": time.time(),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _clear_progress() -> None:
    path = _progress_path()
    if path.exists():
        path.unlink()


def _make_embedding_batches(chunks: list[Document]) -> list[list[Document]]:
    """Batchuje podle počtu chunků i odhadovaného token countu."""
    max_items = min(max(1, config.OPENAI_EMBED_BATCH_SIZE), 16) if config.EMBEDDING_BACKEND == "openai" else min(max(1, config.OLLAMA_EMBED_BATCH_SIZE), 16)
    max_tokens = _OPENAI_MAX_BATCH_TOKENS if config.EMBEDDING_BACKEND == "openai" else 10**9
    batches: list[list[Document]] = []
    current: list[Document] = []
    current_tokens = 0
    for chunk in chunks:
        tokens = _approx_tokens(chunk.page_content)
        if current and (len(current) >= max_items or current_tokens + tokens > max_tokens):
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(chunk)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _is_rate_limit_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return "ratelimit" in name or "rate_limit" in message or "rate limit" in message or "429" in message


def _is_transient_embedding_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    transient_markers = (
        "readtimeout", "timeout", "timed out", "temporarily unavailable",
        "connection", "connecterror", "remoteprotocolerror", "server disconnected",
        "503", "502", "504", "500",
    )
    return _is_rate_limit_error(exc) or any(marker in name or marker in message for marker in transient_markers)


def _embed_batch_with_retry(embeddings, texts: list[str], batch_index: int, batch_tokens: int, metrics: dict) -> list[list[float]]:
    attempt = 0
    while True:
        try:
            vectors = embeddings.embed_documents(texts)
            metrics["requests"].append(time.time())
            metrics["tokens"].append((time.time(), batch_tokens))
            return vectors
        except Exception as exc:
            if not _is_transient_embedding_error(exc) or attempt >= config.OPENAI_EMBED_MAX_RETRIES:
                metrics["failed_batches"] += 1
                raise
            attempt += 1
            metrics["retry_count"] += 1
            retry_after = _retry_after_seconds(exc)
            if retry_after is None:
                retry_after = min(120.0, (2 ** attempt) + random.uniform(0, 2.0))
            logger.warning(
                f"Embedding transient error batch={batch_index}, retry={attempt}/{config.OPENAI_EMBED_MAX_RETRIES}, "
                f"error={exc.__class__.__name__}: {exc}, čekám {retry_after:.1f}s, "
                f"estimated_tokens={batch_tokens}"
            )
            time.sleep(retry_after)


def _log_openai_throughput(batch_index: int, total_batches: int, batch_size: int, batch_tokens: int, metrics: dict) -> None:
    now = time.time()
    while metrics["requests"] and now - metrics["requests"][0] > 60:
        metrics["requests"].popleft()
    while metrics["tokens"] and now - metrics["tokens"][0][0] > 60:
        metrics["tokens"].popleft()
    rpm = len(metrics["requests"])
    tpm = sum(tokens for _ts, tokens in metrics["tokens"])
    logger.info(
        f"OpenAI embeddings batch {batch_index + 1}/{total_batches}: "
        f"chunks={batch_size}, estimated_tokens={batch_tokens}, "
        f"requests/min={rpm}, estimated_TPM={tpm}, retries={metrics['retry_count']}"
    )


def _make_points(batch_chunks: list[Document], batch_vecs: list[list[float]]) -> list:
    qmodels = _qmodels()
    points = []
    for chunk, vec in zip(batch_chunks, batch_vecs):
        cid = chunk.metadata.get("chunk_id", "")
        if cid:
            point_id = _chunk_id_to_point_id(cid)
        else:
            point_id = int(hashlib.sha256(chunk.page_content[:100].encode()).hexdigest()[:16], 16)

        points.append(qmodels.PointStruct(
            id=point_id,
            vector=vec,
            payload={"page_content": chunk.page_content, **chunk.metadata},
        ))
    return points


def _flush_gc(stage: str) -> None:
    collected = gc.collect()
    logger.info(f"GC flush stage={stage}: collected={collected}, rss={_rss_mb():.1f} MB")


# ---------------------------------------------------------------------------
# Správa kolekce
# ---------------------------------------------------------------------------

def _collection_exists(client: QdrantClient) -> bool:
    names = {c.name for c in client.get_collections().collections}
    return config.QDRANT_COLLECTION in names


def _ensure_collection_exists(client: QdrantClient) -> None:
    """Vytvoří kolekci pokud neexistuje. Existující kolekci netkne."""
    if _collection_exists(client):
        return
    qmodels = _qmodels()
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=config.QDRANT_VECTOR_SIZE,
            distance=qmodels.Distance.COSINE,
        ),
    )
    logger.info(f"Kolekce '{config.QDRANT_COLLECTION}' vytvořena")


def _recreate_collection(client: QdrantClient) -> None:
    """Smaže a znovu vytvoří kolekci (full reindex)."""
    if _collection_exists(client):
        client.delete_collection(config.QDRANT_COLLECTION)
        logger.warning(f"Kolekce '{config.QDRANT_COLLECTION}' smazána (full reindex)")
    qmodels = _qmodels()
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=config.QDRANT_VECTOR_SIZE,
            distance=qmodels.Distance.COSINE,
        ),
    )
    logger.info(f"Kolekce '{config.QDRANT_COLLECTION}' vytvořena")


# ---------------------------------------------------------------------------
# Detekce existujících chunk_ids (pro incremental)
# ---------------------------------------------------------------------------

def get_existing_chunk_ids(client: QdrantClient) -> set[str]:
    """
    Načte množinu všech chunk_id z existující Qdrant kolekce.

    Používá scroll API v dávkách _SCROLL_BATCH_SIZE.
    Pro 18 000 bodů → ~18 HTTP volání (každé ~1000 bodů).
    Načítá pouze payload pole 'chunk_id' (ne vektory) pro minimální přenos.

    Returns:
        Množina chunk_id řetězců. Prázdná množina pokud kolekce neexistuje.
    """
    if not _collection_exists(client):
        return set()

    existing: set[str] = set()
    offset = None

    while True:
        result, next_offset = client.scroll(
            collection_name=config.QDRANT_COLLECTION,
            limit=_SCROLL_BATCH_SIZE,
            offset=offset,
            with_payload=["chunk_id"],
            with_vectors=False,
        )

        for point in result:
            cid = (point.payload or {}).get("chunk_id")
            if cid:
                existing.add(cid)

        if next_offset is None:
            break
        offset = next_offset

    return existing


def filter_new_chunks(
    chunks: list[Document],
    existing_ids: set[str],
) -> tuple[list[Document], int]:
    """
    Rozdělí chunky na nové (k indexaci) a existující (k přeskočení).

    Chunk bez chunk_id v metadatech je vždy považován za nový.

    Returns:
        (new_chunks, skipped_count)
    """
    new_chunks = []
    skipped = 0

    for chunk in chunks:
        cid = chunk.metadata.get("chunk_id")
        if cid and cid in existing_ids:
            skipped += 1
        else:
            new_chunks.append(chunk)

    return new_chunks, skipped


# ---------------------------------------------------------------------------
# Qdrant indexace
# ---------------------------------------------------------------------------

def _embed_and_upsert(
    chunks: list[Document],
    client: QdrantClient,
    embeddings,
    resume: bool = False,
) -> dict:
    """
    Embedduje chunky a vloží je do Qdrant.

    Point ID = deterministický uint64 odvozený z chunk_id.
    Chunky bez chunk_id dostanou fallback hash z prvních 100 znaků obsahu.
    """
    if not chunks:
        return {"indexed": 0, "failed": 0, "indexed_chunk_ids": [], "failed_chunk_ids": [], "retry_count": 0}

    chunks = _guard_embed_chunks(chunks)
    texts = [c.page_content for c in chunks]

    logger.info(
        f"Embedduju {len(texts)} chunků "
        f"(backend: {config.EMBEDDING_BACKEND}, model: {config.get_active_embed_model()}, "
        f"dim: {config.QDRANT_VECTOR_SIZE})…"
    )
    batches = _make_embedding_batches(chunks)
    progress = _load_progress() if resume else {"last_successful_batch": -1, "completed_chunk_ids": [], "failed_chunk_ids": []}
    last_successful = int(progress.get("last_successful_batch", -1))
    completed_chunk_ids = list(progress.get("completed_chunk_ids", []))
    failed_chunk_ids = list(progress.get("failed_chunk_ids", []))
    completed_set = set(completed_chunk_ids)
    run_completed_chunk_ids: list[str] = []
    if resume and last_successful >= 0:
        logger.info(
            f"Resume embedding progress: poslední hotový batch={last_successful}, "
            f"({len(completed_chunk_ids)} chunků)"
        )

    metrics = {"requests": deque(), "tokens": deque(), "retry_count": 0, "failed_batches": 0}
    sleep_s = max(0, config.OPENAI_EMBED_SLEEP_MS) / 1000

    logger.info(
        f"Embedding batches: {len(batches)} "
        f"(backend={config.EMBEDDING_BACKEND}, max_batch_size="
        f"{min(max(1, config.OPENAI_EMBED_BATCH_SIZE), 16) if config.EMBEDDING_BACKEND == 'openai' else min(max(1, config.OLLAMA_EMBED_BATCH_SIZE), 16)}, "
        f"timeout={config.OPENAI_EMBED_TIMEOUT_SECONDS if config.EMBEDDING_BACKEND == 'openai' else 'backend-default'}s, "
        f"qdrant_flush=per_batch)"
    )

    for batch_index, batch_chunks in enumerate(tqdm(batches, desc="Embedding+Qdrant upsert")):
        if resume and completed_set:
            batch_chunks = [c for c in batch_chunks if c.metadata.get("chunk_id") not in completed_set]
        if not batch_chunks:
            continue
        batch_texts = [c.page_content for c in batch_chunks]
        batch_tokens = sum(_approx_tokens(text) for text in batch_texts)

        try:
            batch_vecs = _embed_batch_with_retry(embeddings, batch_texts, batch_index, batch_tokens, metrics)
        except Exception:
            failed_now = [c.metadata.get("chunk_id", "") for c in batch_chunks if c.metadata.get("chunk_id")]
            failed_chunk_ids.extend(failed_now)
            _save_progress(batch_index - 1, completed_chunk_ids, failed_chunk_ids)
            logger.exception(
                f"Embedding batch failed permanently batch={batch_index + 1}/{len(batches)}, "
                f"failed_chunks_total={len(failed_chunk_ids)}, indexed_chunks={len(completed_chunk_ids)}, "
                f"retry_count={metrics['retry_count']}. Checkpoint uložen pro resume."
            )
            raise

        if config.EMBEDDING_BACKEND == "openai":
            _log_openai_throughput(batch_index, len(batches), len(batch_chunks), batch_tokens, metrics)
            if sleep_s:
                time.sleep(sleep_s)

        points = _make_points(batch_chunks, batch_vecs)
        client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
        del points, batch_vecs, batch_texts
        new_completed = [c.metadata.get("chunk_id", "") for c in batch_chunks if c.metadata.get("chunk_id")]
        completed_chunk_ids.extend(new_completed)
        run_completed_chunk_ids.extend(new_completed)
        completed_set.update(new_completed)
        if failed_chunk_ids:
            recovered_now = set(new_completed)
            failed_chunk_ids = [cid for cid in failed_chunk_ids if cid not in recovered_now]
        _save_progress(batch_index, completed_chunk_ids, failed_chunk_ids)
        logger.info(
            f"Qdrant flush hotový batch={batch_index + 1}/{len(batches)}, "
            f"batch_chunks={len(batch_chunks)}, indexed_chunks={len(completed_chunk_ids)}, "
            f"failed_chunks={len(failed_chunk_ids)}, retry_count={metrics['retry_count']}"
        )
        _flush_gc(f"embedding_batch_{batch_index + 1}")

    return {
        "indexed": len(run_completed_chunk_ids),
        "failed": len(failed_chunk_ids),
        "indexed_chunk_ids": run_completed_chunk_ids,
        "checkpoint_completed_total": len(completed_chunk_ids),
        "failed_chunk_ids": failed_chunk_ids,
        "retry_count": metrics["retry_count"],
    }


def index_to_qdrant(
    chunks: list[Document],
    client: QdrantClient | None = None,
    embeddings = None,
    resume: bool = False,
) -> None:
    """
    Vloží chunky do Qdrant (full mode – přepíše existující kolekci).
    Zachováno pro zpětnou kompatibilitu; preferujte run_full_indexing().
    """
    client = client or _get_qdrant_client()
    embeddings = embeddings or _get_embeddings()
    if resume:
        _ensure_collection_exists(client)
        logger.info("Resume režim: Qdrant kolekci nepřepisuji, pokračuji v rozpracované indexaci")
        existing_ids = get_existing_chunk_ids(client)
        if existing_ids:
            chunks, skipped = filter_new_chunks(chunks, existing_ids)
            logger.info(f"Resume: existující Qdrant body nepřepisuji, přeskočeno podle chunk_id: {skipped}")
    else:
        _clear_progress()
        _recreate_collection(client)
    _embed_and_upsert(chunks, client, embeddings, resume=resume)
    logger.info(f"Qdrant: {len(chunks)} bodů indexováno do '{config.QDRANT_COLLECTION}'")


# ---------------------------------------------------------------------------
# BM25 indexace
# ---------------------------------------------------------------------------

def save_bm25_index(chunks: list[Document]) -> None:
    """Vytvoří BM25 index z chunks a uloží na disk (full mode)."""
    from rank_bm25 import BM25Okapi

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    chunks = _replace_structured_pricing_bm25_docs(chunks)
    tokenized = [_tokenize_bm25(_bm25_searchable_text(c)) for c in chunks]
    bm25 = BM25Okapi(tokenized)

    with open(config.BM25_INDEX_PATH, "wb") as f:
        pickle.dump(bm25, f)
    with open(config.DOCS_STORE_PATH, "wb") as f:
        pickle.dump(chunks, f)

    logger.info(f"BM25 index uložen: {config.BM25_INDEX_PATH} ({len(chunks)} dokumentů)")


def update_bm25_index(new_chunks: list[Document]) -> int:
    """
    Přidá nové chunky do existujícího BM25 indexu.

    Workflow:
      1. Načte existující dokumenty z pickle (pokud existuje)
      2. Deduplikuje podle chunk_id (zabrání duplicitám při opakovaném volání)
      3. Připojí nové chunky
      4. Přebuduje BM25 ze sloučené množiny
      5. Uloží obojí zpět na disk

    Returns:
        Celkový počet dokumentů v aktualizovaném indexu.
    """
    from rank_bm25 import BM25Okapi

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Načteme existující dokumenty
    existing_chunks: list[Document] = []
    if config.DOCS_STORE_PATH.exists():
        with open(config.DOCS_STORE_PATH, "rb") as f:
            existing_chunks = pickle.load(f)

    # JSONL pricing rows are regenerated on every BM25 rebuild so stale rows do
    # not remain in documents.pkl after pricing_rows.jsonl changes.
    existing_chunks = [
        c for c in existing_chunks
        if not (
            c.metadata.get("source_type") == "structured_pricing_row"
            or str(c.metadata.get("chunk_id") or "").startswith("pricing_row_jsonl:")
        )
    ]

    # Deduplikace: sestavíme množinu existujících chunk_id
    existing_ids = {
        c.metadata.get("chunk_id")
        for c in existing_chunks
        if c.metadata.get("chunk_id")
    }

    truly_new = [
        c for c in new_chunks
        if not c.metadata.get("chunk_id") or c.metadata["chunk_id"] not in existing_ids
    ]

    all_chunks = _replace_structured_pricing_bm25_docs(existing_chunks + truly_new)
    tokenized = [_tokenize_bm25(_bm25_searchable_text(c)) for c in all_chunks]
    bm25 = BM25Okapi(tokenized)

    with open(config.BM25_INDEX_PATH, "wb") as f:
        pickle.dump(bm25, f)
    with open(config.DOCS_STORE_PATH, "wb") as f:
        pickle.dump(all_chunks, f)

    logger.info(
        f"BM25 aktualizován: +{len(truly_new)} nových "
        f"→ celkem {len(all_chunks)} dokumentů"
    )
    return len(all_chunks)


def append_bm25_docs_store_memory_safe(new_chunks: list[Document]) -> int:
    """Memory-safe BM25 companion flush.

    BM25Okapi itself is not appendable without rebuilding the full token matrix.
    In memory-safe mode we therefore persist newly indexed docs to a JSONL sidecar
    per batch and avoid rebuilding the whole BM25 object during the OOM-sensitive
    ingest run. Dense Qdrant retrieval is immediately updated; BM25 rebuild can be
    run later outside memory-safe mode if needed.
    """
    if not new_chunks:
        return 0
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    sidecar = config.INDEX_DIR / "bm25_incremental_pending.jsonl"
    with sidecar.open("a", encoding="utf-8") as f:
        for chunk in new_chunks:
            f.write(json.dumps({"page_content": chunk.page_content, "metadata": chunk.metadata}, ensure_ascii=False) + "\n")
    logger.info(f"BM25 memory-safe flush: +{len(new_chunks)} docs → {sidecar} (BM25 rebuild deferred)")
    _flush_gc("bm25_memory_safe_flush")
    try:
        if config.DOCS_STORE_PATH.exists():
            with open(config.DOCS_STORE_PATH, "rb") as f:
                existing_count = len(pickle.load(f))
            return existing_count + len(new_chunks)
    except Exception as exc:
        logger.warning(f"Nelze spočítat existující BM25 docs store: {exc}")
    return len(new_chunks)


# ---------------------------------------------------------------------------
# Hlavní entry points
# ---------------------------------------------------------------------------

def run_incremental_indexing(chunks: list[Document]) -> dict:
    """
    Incremental indexace: přidává pouze nové chunky.

    Algoritmus:
      1. Načte existující chunk_id z Qdrant (scroll)
      2. Vyfiltruje chunky které již existují
      3. Embedduje a indexuje pouze nové chunky do Qdrant
      4. Aktualizuje BM25 pickle (merge, ne rebuild)

    Returns:
        Dict se statistikami: new, skipped, total_qdrant, total_bm25.
    """
    if not chunks:
        logger.error("Prázdný seznam chunků – indexace přerušena")
        return {"new": 0, "skipped": 0, "total_qdrant": 0, "total_bm25": 0}

    chunks = _guard_embed_chunks(chunks)
    progress = _load_progress()
    resume_completed_ids = {
        cid for cid in progress.get("completed_chunk_ids", []) if cid
    }
    if resume_completed_ids:
        logger.info(
            f"Incremental resume checkpoint nalezen: {len(resume_completed_ids)} chunků už bylo upsertováno; "
            "po ověření Qdrant doplním BM25 a budu pokračovat zbytkem."
        )

    client = _get_qdrant_client()
    embeddings = _get_embeddings()

    # Krok 1: Zajistíme existenci kolekce (nevymaže existující)
    _ensure_collection_exists(client)

    # Krok 2: Zjistíme co už je v Qdrantu
    logger.info("Načítám existující chunk_id z Qdrantu…")
    existing_ids = get_existing_chunk_ids(client)
    logger.info(f"  Qdrant obsahuje {len(existing_ids)} existujících chunk_id")

    recovery_chunks = []
    if resume_completed_ids:
        recovery_chunks = [
            c for c in chunks
            if c.metadata.get("chunk_id") in resume_completed_ids and c.metadata.get("chunk_id") in existing_ids
        ]
        if recovery_chunks:
            logger.info(
                f"Resume recovery: {len(recovery_chunks)} checkpointovaných chunků je v Qdrantu; "
                "zařazuji je pro BM25 merge kvůli předchozímu pádu před BM25."
            )

    # Krok 3: Filtrujeme nové chunky
    new_chunks, skipped = filter_new_chunks(chunks, existing_ids)
    logger.info(
        f"  Nových chunků k indexaci: {len(new_chunks)}, "
        f"přeskočeno (duplikáty): {skipped}"
    )

    # Krok 4: Indexujeme nové chunky do Qdrant
    embed_stats = {"indexed": 0, "failed": 0, "indexed_chunk_ids": [], "failed_chunk_ids": [], "retry_count": 0}
    if new_chunks:
        embed_stats = _embed_and_upsert(new_chunks, client, embeddings, resume=True)
    else:
        logger.info("Žádné nové chunky – Qdrant je aktuální")

    # Krok 5: Aktualizujeme BM25
    indexed_ids = set(embed_stats.get("indexed_chunk_ids", []))
    bm25_chunks = recovery_chunks + [c for c in new_chunks if c.metadata.get("chunk_id") in indexed_ids or not c.metadata.get("chunk_id")]
    total_bm25 = update_bm25_index(bm25_chunks)
    _clear_progress()

    # Celkový počet bodů v Qdrantu
    total_qdrant = client.get_collection(config.QDRANT_COLLECTION).points_count or 0

    logger.info(
        "[bold green]Incremental indexace dokončena[/bold green] — "
        f"nové: {len(new_chunks)}, přeskočeno: {skipped}, "
        f"Qdrant celkem: {total_qdrant}"
    )
    return {
        "new": len(new_chunks),
        "indexed": embed_stats.get("indexed", 0),
        "failed": embed_stats.get("failed", 0),
        "retry_count": embed_stats.get("retry_count", 0),
        "recovered_for_bm25": len(recovery_chunks),
        "skipped": skipped,
        "total_qdrant": total_qdrant,
        "total_bm25": total_bm25,
    }


def run_incremental_indexing_stream(chunk_batches, *, memory_safe: bool = True) -> dict:
    """Incremental indexing over lazy chunk batches.

    Does not recreate/delete Qdrant collection. Designed for OOM-sensitive ingest:
    one chunk batch is embedded/upserted/flushed at a time and then released.
    """
    client = _get_qdrant_client()
    embeddings = _get_embeddings()
    _ensure_collection_exists(client)
    logger.info("Memory-safe incremental index: načítám existující chunk_id z Qdrantu…")
    existing_ids = get_existing_chunk_ids(client)
    logger.info(f"Memory-safe incremental index: Qdrant obsahuje {len(existing_ids)} chunk_id")
    log_memory("stream_start_after_existing_ids")

    progress = _load_progress()
    resume_completed_ids = {cid for cid in progress.get("completed_chunk_ids", []) if cid}
    total_seen = 0
    total_new = 0
    total_skipped = 0
    total_indexed = 0
    total_failed = 0
    total_retries = 0
    total_bm25 = 0
    recovered_for_bm25 = 0

    for batch_no, batch in enumerate(chunk_batches, start=1):
        log_memory(f"stream_batch_{batch_no}_received")
        if not batch:
            continue
        total_seen += len(batch)

        recovery_chunks = []
        if resume_completed_ids:
            recovery_chunks = [
                c for c in batch
                if c.metadata.get("chunk_id") in resume_completed_ids and c.metadata.get("chunk_id") in existing_ids
            ]
            recovered_for_bm25 += len(recovery_chunks)

        new_chunks, skipped = filter_new_chunks(batch, existing_ids)
        total_new += len(new_chunks)
        total_skipped += skipped
        logger.info(
            f"Memory-safe batch {batch_no}: received={len(batch)}, new={len(new_chunks)}, "
            f"skipped={skipped}, recovered_for_bm25={len(recovery_chunks)}"
        )

        embed_stats = {"indexed": 0, "failed": 0, "indexed_chunk_ids": [], "failed_chunk_ids": [], "retry_count": 0}
        if new_chunks:
            embed_stats = _embed_and_upsert(new_chunks, client, embeddings, resume=True)
            indexed_ids = set(embed_stats.get("indexed_chunk_ids", []))
            existing_ids.update(indexed_ids)
        else:
            indexed_ids = set()

        bm25_chunks = recovery_chunks + [
            c for c in new_chunks
            if c.metadata.get("chunk_id") in indexed_ids or not c.metadata.get("chunk_id")
        ]
        if memory_safe:
            total_bm25 = append_bm25_docs_store_memory_safe(bm25_chunks)
        else:
            total_bm25 = update_bm25_index(bm25_chunks)

        total_indexed += int(embed_stats.get("indexed", 0))
        total_failed += int(embed_stats.get("failed", 0))
        total_retries += int(embed_stats.get("retry_count", 0))
        logger.info(
            f"Memory-safe progress batch={batch_no}: total_seen={total_seen}, "
            f"total_indexed={total_indexed}, total_failed={total_failed}, retries={total_retries}"
        )
        del batch, new_chunks, bm25_chunks, recovery_chunks
        _flush_gc(f"stream_batch_{batch_no}_done")

    _clear_progress()
    total_qdrant = client.get_collection(config.QDRANT_COLLECTION).points_count or 0
    return {
        "new": total_new,
        "indexed": total_indexed,
        "failed": total_failed,
        "retry_count": total_retries,
        "recovered_for_bm25": recovered_for_bm25,
        "skipped": total_skipped,
        "total_qdrant": total_qdrant,
        "total_bm25": total_bm25,
    }


def run_full_indexing(chunks: list[Document], resume: bool = False) -> None:
    """
    Kompletní reindexace od nuly: smaže a znovu vytvoří kolekci.

    Použijte pokud:
      - Měníte embedding model (dimenze vektoru)
      - Měníte chunking parametry
      - Chcete odstranit smazané/přejmenované soubory z indexu
    """
    if not chunks:
        logger.error("Prázdný seznam chunků – indexace přerušena")
        return

    chunks = _guard_embed_chunks(chunks)

    client = _get_qdrant_client()
    embeddings = _get_embeddings()

    index_to_qdrant(chunks, client=client, embeddings=embeddings, resume=resume)
    save_bm25_index(chunks)
    _clear_progress()

    logger.info("[bold green]Full indexace dokončena úspěšně[/bold green]")

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
from pathlib import Path

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from tqdm import tqdm

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

_UPSERT_BATCH_SIZE = 64
_SCROLL_BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# Klientské singletons
# ---------------------------------------------------------------------------

def _get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBED_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def _get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)


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
    embeddings: OllamaEmbeddings,
) -> None:
    """
    Embedduje chunky a vloží je do Qdrant.

    Point ID = deterministický uint64 odvozený z chunk_id.
    Chunky bez chunk_id dostanou fallback hash z prvních 100 znaků obsahu.
    """
    if not chunks:
        return

    texts = [c.page_content for c in chunks]

    logger.info(f"Embedduju {len(texts)} chunků (model: {config.EMBED_MODEL})…")
    vectors: list[list[float]] = []
    for i in tqdm(range(0, len(texts), _UPSERT_BATCH_SIZE), desc="Embedding"):
        batch_vecs = embeddings.embed_documents(texts[i : i + _UPSERT_BATCH_SIZE])
        vectors.extend(batch_vecs)

    logger.info(f"Ukládám {len(chunks)} bodů do Qdrant…")
    for i in tqdm(range(0, len(chunks), _UPSERT_BATCH_SIZE), desc="Qdrant upsert"):
        batch_chunks = chunks[i : i + _UPSERT_BATCH_SIZE]
        batch_vecs = vectors[i : i + _UPSERT_BATCH_SIZE]

        points = []
        for chunk, vec in zip(batch_chunks, batch_vecs):
            cid = chunk.metadata.get("chunk_id", "")
            # Deterministické point ID: hex chunk_id → uint64
            # Fallback pro chunky bez chunk_id: hash obsahu
            if cid:
                point_id = _chunk_id_to_point_id(cid)
            else:
                import hashlib
                point_id = int(hashlib.sha256(chunk.page_content[:100].encode()).hexdigest()[:16], 16)

            points.append(qmodels.PointStruct(
                id=point_id,
                vector=vec,
                payload={
                    "page_content": chunk.page_content,
                    **chunk.metadata,
                },
            ))

        client.upsert(
            collection_name=config.QDRANT_COLLECTION,
            points=points,
        )


def index_to_qdrant(
    chunks: list[Document],
    client: QdrantClient | None = None,
    embeddings: OllamaEmbeddings | None = None,
) -> None:
    """
    Vloží chunky do Qdrant (full mode – přepíše existující kolekci).
    Zachováno pro zpětnou kompatibilitu; preferujte run_full_indexing().
    """
    client = client or _get_qdrant_client()
    embeddings = embeddings or _get_embeddings()
    _recreate_collection(client)
    _embed_and_upsert(chunks, client, embeddings)
    logger.info(f"Qdrant: {len(chunks)} bodů indexováno do '{config.QDRANT_COLLECTION}'")


# ---------------------------------------------------------------------------
# BM25 indexace
# ---------------------------------------------------------------------------

def save_bm25_index(chunks: list[Document]) -> None:
    """Vytvoří BM25 index z chunks a uloží na disk (full mode)."""
    from rank_bm25 import BM25Okapi

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tokenized = [c.page_content.lower().split() for c in chunks]
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

    all_chunks = existing_chunks + truly_new
    tokenized = [c.page_content.lower().split() for c in all_chunks]
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

    client = _get_qdrant_client()
    embeddings = _get_embeddings()

    # Krok 1: Zajistíme existenci kolekce (nevymaže existující)
    _ensure_collection_exists(client)

    # Krok 2: Zjistíme co už je v Qdrantu
    logger.info("Načítám existující chunk_id z Qdrantu…")
    existing_ids = get_existing_chunk_ids(client)
    logger.info(f"  Qdrant obsahuje {len(existing_ids)} existujících chunk_id")

    # Krok 3: Filtrujeme nové chunky
    new_chunks, skipped = filter_new_chunks(chunks, existing_ids)
    logger.info(
        f"  Nových chunků k indexaci: {len(new_chunks)}, "
        f"přeskočeno (duplikáty): {skipped}"
    )

    # Krok 4: Indexujeme nové chunky do Qdrant
    if new_chunks:
        _embed_and_upsert(new_chunks, client, embeddings)
    else:
        logger.info("Žádné nové chunky – Qdrant je aktuální")

    # Krok 5: Aktualizujeme BM25
    total_bm25 = update_bm25_index(new_chunks)

    # Celkový počet bodů v Qdrantu
    total_qdrant = client.get_collection(config.QDRANT_COLLECTION).points_count or 0

    logger.info(
        "[bold green]Incremental indexace dokončena[/bold green] — "
        f"nové: {len(new_chunks)}, přeskočeno: {skipped}, "
        f"Qdrant celkem: {total_qdrant}"
    )
    return {
        "new": len(new_chunks),
        "skipped": skipped,
        "total_qdrant": total_qdrant,
        "total_bm25": total_bm25,
    }


def run_full_indexing(chunks: list[Document]) -> None:
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

    client = _get_qdrant_client()
    embeddings = _get_embeddings()

    index_to_qdrant(chunks, client=client, embeddings=embeddings)
    save_bm25_index(chunks)

    logger.info("[bold green]Full indexace dokončena úspěšně[/bold green]")

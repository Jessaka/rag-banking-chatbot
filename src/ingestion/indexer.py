"""
Indexace chunků do Qdrant (dense) a BM25 (sparse).

Workflow:
  1. Embed každý chunk pomocí Ollama nomic-embed-text
  2. Uloží vektory + metadata do Qdrant kolekce
  3. Uloží BM25 index + surové dokumenty na disk (pickle)

Idempotentní: opakované spuštění přepíše existující kolekci.
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

# Počet chunků odeslaných do Qdrant v jednom HTTP volání
_UPSERT_BATCH_SIZE = 64


def _get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBED_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def _get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)


def _recreate_collection(client: QdrantClient) -> None:
    """Smaže a znovu vytvoří kolekci s cosine vzdáleností."""
    existing = [c.name for c in client.get_collections().collections]
    if config.QDRANT_COLLECTION in existing:
        logger.warning(
            f"Kolekce '{config.QDRANT_COLLECTION}' existuje – přepisuju"
        )
        client.delete_collection(config.QDRANT_COLLECTION)

    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=config.QDRANT_VECTOR_SIZE,
            distance=qmodels.Distance.COSINE,
        ),
    )
    logger.info(f"Kolekce '{config.QDRANT_COLLECTION}' vytvořena")


def index_to_qdrant(
    chunks: list[Document],
    client: QdrantClient | None = None,
    embeddings: OllamaEmbeddings | None = None,
) -> None:
    """
    Vloží chunky do Qdrant.

    Args:
        chunks:     Chunky připravené k indexaci.
        client:     Existující Qdrant klient (nebo None → nový).
        embeddings: Existující embeddings model (nebo None → nový).
    """
    client = client or _get_qdrant_client()
    embeddings = embeddings or _get_embeddings()

    _recreate_collection(client)

    texts = [c.page_content for c in chunks]

    logger.info(f"Embedduju {len(texts)} chunků (model: {config.EMBED_MODEL})…")
    vectors: list[list[float]] = []
    for i in tqdm(range(0, len(texts), _UPSERT_BATCH_SIZE), desc="Embedding"):
        batch_texts = texts[i : i + _UPSERT_BATCH_SIZE]
        batch_vecs = embeddings.embed_documents(batch_texts)
        vectors.extend(batch_vecs)

    logger.info("Ukládám do Qdrant…")
    for i in tqdm(range(0, len(chunks), _UPSERT_BATCH_SIZE), desc="Qdrant upsert"):
        batch_chunks = chunks[i : i + _UPSERT_BATCH_SIZE]
        batch_vecs = vectors[i : i + _UPSERT_BATCH_SIZE]

        points = [
            qmodels.PointStruct(
                id=idx + i,
                vector=vec,
                payload={
                    "page_content": chunk.page_content,
                    **chunk.metadata,
                },
            )
            for idx, (chunk, vec) in enumerate(zip(batch_chunks, batch_vecs))
        ]
        client.upsert(
            collection_name=config.QDRANT_COLLECTION,
            points=points,
        )

    logger.info(f"Qdrant: {len(chunks)} bodů indexováno do '{config.QDRANT_COLLECTION}'")


def save_bm25_index(chunks: list[Document]) -> None:
    """
    Vytvoří a uloží BM25 index + dokumenty na disk.

    BM25 tokenizuje text lowercasem a rozděluje na slova (whitespace).
    Pro produkci lze nahradit sofistikovanějším Czech tokenizerem.
    """
    from rank_bm25 import BM25Okapi

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)

    tokenized = [
        chunk.page_content.lower().split() for chunk in chunks
    ]
    bm25 = BM25Okapi(tokenized)

    with open(config.BM25_INDEX_PATH, "wb") as f:
        pickle.dump(bm25, f)

    with open(config.DOCS_STORE_PATH, "wb") as f:
        pickle.dump(chunks, f)

    logger.info(
        f"BM25 index uložen: {config.BM25_INDEX_PATH} "
        f"({len(chunks)} dokumentů)"
    )


def run_full_indexing(chunks: list[Document]) -> None:
    """
    Kompletní indexace: Qdrant + BM25.

    Args:
        chunks: Připravené chunky z chunker.chunk_documents().
    """
    if not chunks:
        logger.error("Prázdný seznam chunků – indexace přerušena")
        return

    client = _get_qdrant_client()
    embeddings = _get_embeddings()

    index_to_qdrant(chunks, client=client, embeddings=embeddings)
    save_bm25_index(chunks)

    logger.info("[bold green]Indexace dokončena úspěšně[/bold green]")

"""
Rozdělení dokumentů na překrývající se chunky.

Používá RecursiveCharacterTextSplitter, který respektuje přirozené
hranice textu (odstavce → věty → slova → znaky).

Každý chunk zdědí metadata z rodičovského dokumentu a dostane
unikátní chunk_id pro sledování v Qdrant.
"""

from __future__ import annotations

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _make_chunk_id(source: str, page: int, chunk_index: int) -> str:
    """Vytvoří deterministické ID chunku z jeho zdrojových souřadnic."""
    raw = f"{source}:p{page}:c{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_documents(
    documents: list[Document],
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
    separators: list[str] = config.CHUNK_SEPARATORS,
) -> list[Document]:
    """
    Rozdělí seznam dokumentů na chunky.

    Args:
        documents:     Vstupní dokumenty (obvykle stránky z PDF parseru).
        chunk_size:    Maximální délka chunku ve znacích.
        chunk_overlap: Překryv sousedních chunků (kontext pro hranice).
        separators:    Prioritizovaný seznam dělících znaků.

    Returns:
        Seznam chunků jako Document objekty s rozšířenými metadaty.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        length_function=len,
        is_separator_regex=False,
    )

    all_chunks: list[Document] = []
    # Čítač chunků per (source, page) pro unikátní ID
    chunk_counters: dict[tuple[str, int], int] = {}

    for doc in documents:
        raw_chunks = splitter.split_documents([doc])

        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)

        for raw_chunk in raw_chunks:
            key = (source, page)
            idx = chunk_counters.get(key, 0)
            chunk_counters[key] = idx + 1

            enriched_metadata = {
                **raw_chunk.metadata,
                "chunk_id": _make_chunk_id(source, page, idx),
                "chunk_index": idx,
                "char_count": len(raw_chunk.page_content),
            }

            all_chunks.append(
                Document(
                    page_content=raw_chunk.page_content,
                    metadata=enriched_metadata,
                )
            )

    logger.info(
        f"Chunking: {len(documents)} dokumentů → {len(all_chunks)} chunků "
        f"(size={chunk_size}, overlap={chunk_overlap})"
    )
    return all_chunks

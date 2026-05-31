"""Index valid playwright mortgage TXT files into Qdrant + BM25."""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from src.ingestion.chunker import chunk_documents
from src.ingestion.indexer import run_incremental_indexing
from src.utils.logger import get_logger

logger = get_logger(__name__)

VALID_FILES = [
    "playwright_hypoteky_osobni_hypoteky.txt",
    "playwright_hypoteky_osobni_hypoteky_americka-hypoteka.txt",
    "playwright_hypoteky_osobni_hypoteky_hypoteka-na-bydleni.txt",
]

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def parse_txt_file(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    url = ""
    for line in lines[:6]:
        if line.startswith("URL:"):
            url = line[4:].strip()
            break

    # Strip header block up to and including the separator line
    sep_idx = next((i for i, l in enumerate(lines) if l.startswith("===")), None)
    if sep_idx is not None:
        content = "\n".join(lines[sep_idx + 1:]).strip()
    else:
        content = text.strip()

    return Document(
        page_content=content,
        metadata={
            "source": url,
            "source_url": url,
            "category": "mortgages",
            "document_type": "product_page",
            "document_year": 2026,
            "language": "cs",
        },
    )


def main():
    docs = []
    for fname in VALID_FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            logger.warning(f"File not found: {fpath}")
            continue
        doc = parse_txt_file(fpath)
        logger.info(f"Parsed {fname}: {len(doc.page_content)} chars, url={doc.metadata['source']}")
        docs.append(doc)

    if not docs:
        logger.error("No documents to index.")
        return

    chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
    logger.info(f"Created {len(chunks)} chunks from {len(docs)} documents")

    stats = run_incremental_indexing(chunks)
    logger.info(f"Indexing complete: {stats}")


if __name__ == "__main__":
    main()

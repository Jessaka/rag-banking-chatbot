"""Index reklamace/contact files into Qdrant + BM25."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from src.ingestion.chunker import chunk_documents
from src.ingestion.indexer import run_incremental_indexing
from src.utils.logger import get_logger

logger = get_logger(__name__)

FILES = [
    ("rb_reklamace_dedicated.txt", "https://www.rb.cz/dulezite-informace/reklamace", "support"),
    ("rb_reklamace_kontakty.txt", "https://www.rb.cz/o-nas/kontakty", "support"),
    ("rb_reklamace_podpora.txt", "https://www.rb.cz/podpora", "support"),
    ("rb_reklamace_bezpecnost_podpora.txt", "https://www.rb.cz/podpora/bezpecnost", "support"),
]

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def parse_txt_file(path: Path, url: str, category: str) -> Document:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Extract URL from header if present
    for line in lines[:6]:
        if line.startswith("URL:"):
            url = line[4:].strip()
            break

    sep_idx = next((i for i, l in enumerate(lines) if l.startswith("===")), None)
    content = "\n".join(lines[sep_idx + 1:]).strip() if sep_idx is not None else text.strip()

    return Document(
        page_content=content,
        metadata={
            "source": url,
            "source_url": url,
            "category": category,
            "document_type": "faq_support_page",
            "document_year": 2026,
            "language": "cs",
            "chunk_type": "faq",
        },
    )


def main():
    docs = []
    for fname, url, category in FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            logger.warning(f"File not found: {fpath}")
            continue
        doc = parse_txt_file(fpath, url, category)
        logger.info(f"Parsed {fname}: {len(doc.page_content)} chars")
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

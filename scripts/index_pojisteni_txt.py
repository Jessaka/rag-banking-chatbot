"""Index rb_pojisteni_*.txt files into Qdrant + BM25 with category=insurance."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from src.ingestion.chunker import chunk_documents
from src.ingestion.indexer import run_incremental_indexing
from src.utils.logger import get_logger

logger = get_logger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

FILES = [
    ("rb_pojisteni_prehled.txt",                "https://www.rb.cz/osobni/pojisteni"),
    ("rb_pojisteni_cestovni.txt",               "https://www.rb.cz/osobni/pojisteni/cestovni-pojisteni"),
    ("rb_pojisteni_cestovni_naplno.txt",        "https://www.rb.cz/osobni/pojisteni/cestovni-pojisteni/cestovni-pojisteni-naplno"),
    ("rb_pojisteni_zivotni.txt",                "https://www.rb.cz/osobni/pojisteni/zivotni-pojisteni"),
    ("rb_pojisteni_majetkove.txt",              "https://www.rb.cz/osobni/pojisteni/majetkove-pojisteni"),
    ("rb_pojisteni_k_produktum.txt",            "https://www.rb.cz/osobni/pojisteni/pojisteni-k-produktum"),
    ("rb_pojisteni_ke_kartam.txt",              "https://www.rb.cz/osobni/pojisteni/pojisteni-k-produktum/pojisteni-ke-kreditnim-kartam"),
    ("rb_pojisteni_splacet_pujcku.txt",         "https://www.rb.cz/osobni/pojisteni/pojisteni-k-produktum/pojisteni-schopnosti-splacet-pujcku"),
    ("rb_pojisteni_urazove_zivotni_vozidla.txt","https://www.rb.cz/osobni/pojisteni/dalsi-pojisteni"),
]


def parse_txt(path: Path, url: str) -> Document:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Extract URL from header if available
    for line in lines[:5]:
        if line.startswith("URL:"):
            url = line[4:].strip()
            break
    sep = next((i for i, l in enumerate(lines) if l.startswith("===")), None)
    content = "\n".join(lines[sep + 1:]).strip() if sep is not None else text.strip()
    return Document(
        page_content=content,
        metadata={
            "source": url,
            "source_url": url,
            "category": "insurance",
            "document_type": "product_page",
            "document_year": 2026,
            "language": "cs",
        },
    )


def main():
    docs = []
    for fname, url in FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            logger.warning(f"Not found: {fpath}")
            continue
        doc = parse_txt(fpath, url)
        logger.info(f"Parsed {fname}: {len(doc.page_content)} chars")
        docs.append(doc)

    if not docs:
        logger.error("No documents.")
        return

    chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
    logger.info(f"Chunks: {len(chunks)} from {len(docs)} docs")
    stats = run_incremental_indexing(chunks)
    logger.info(f"Done: {stats}")


if __name__ == "__main__":
    main()

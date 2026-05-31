import json
import sys
from pathlib import Path

# Import internal functions (they are not part of public API but we can access)
from src.ingestion.pricing_extractor import (
    extract_pricing_rows_from_pdf,
    _reset_extraction_debug,
    EXTRACTION_DEBUG,
    _extract_tables_with_fallback,
)

def debug_extract(pdf_path: Path):
    # Reset debug counters
    _reset_extraction_debug()
    # Run extraction (metadata empty)
    rows = extract_pricing_rows_from_pdf(pdf_path)
    # Get tables detected via fallback method (same as used inside extraction)
    tables = _extract_tables_with_fallback(str(pdf_path))
    tables_detected = len(tables)
    rows_extracted = len(rows)
    # The extractor already filters rows, so rejected rows are in debug dict
    rows_filtered = EXTRACTION_DEBUG.get("rejected_rows_count", 0)
    # Collect detailed reasons counts
    filter_reasons = {k: v for k, v in EXTRACTION_DEBUG.items() if k != "rejected_rows_count"}
    result = {
        "file": str(pdf_path),
        "tables_detected": tables_detected,
        "rows_extracted": rows_extracted,
        "rows_filtered": rows_filtered,
        "filter_reasons": filter_reasons,
    }
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "PDF path required"}))
        sys.exit(1)
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(json.dumps({"error": f"File not found: {pdf_path}"}))
        sys.exit(1)
    out = debug_extract(pdf_path)
    print(json.dumps(out, ensure_ascii=False, indent=2))

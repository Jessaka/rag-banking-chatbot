import json

from src.ingestion.pricing_extractor import _row_to_pricing_records
from src.retrieval import pricing_retriever


def test_structured_pricing_rejects_broken_or_valueless_rows():
    headers = ["Název položky", "eKonto", "eKonto EXCLUSIVE"]
    broken = _row_to_pricing_records(
        headers,
        ["V e d e n í ú č t u", "z d a r m a", ""],
        source_url="https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        source_file="cenik-pi.pdf",
        page=1,
        table_index=0,
        row_index=1,
        title="Nový ceník",
    )
    no_value = _row_to_pricing_records(
        headers,
        ["Vedení účtu", "dle podmínek", "individuálně"],
        source_url="https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        source_file="cenik-pi.pdf",
        page=1,
        table_index=0,
        row_index=2,
        title="Nový ceník",
    )
    assert broken == []
    assert no_value == []


def test_structured_pricing_normalizes_rows():
    rows = _row_to_pricing_records(
        ["Název položky", "eKonto", "eKonto EXCLUSIVE"],
        ["Vedení účtu", "129 Kč měsíčně", "zdarma"],
        source_url="https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        source_file="cenik-pi.pdf",
        page=4,
        table_index=0,
        row_index=1,
        title="Nový ceník",
    )
    assert len(rows) == 2
    assert rows[0].product_name == "eKonto"
    assert rows[0].fee_type == "Vedení účtu"
    assert rows[0].fee_value == "129 Kč"
    assert rows[0].currency == "CZK"
    assert rows[0].period == "měsíčně"
    assert rows[0].confidence >= 0.70
    assert rows[1].product_name == "eKonto EXCLUSIVE"
    assert rows[1].fee_value == "zdarma"


def test_structured_pricing_blacklists_notes_conditions_and_campaign_rows():
    headers = ["Název položky", "eKonto"]
    for fee_type in [
        "Poznámka ke službě",
        "Splnění podmínek pro bonus",
        "Cena při aktivním využívání účtu",
        "Příjem na účet",
        "Kreditní obrat",
    ]:
        rows = _row_to_pricing_records(
            headers,
            [fee_type, "zdarma"],
            source_url="https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
            source_file="cenik-pi.pdf",
            page=1,
            table_index=0,
            row_index=1,
            title="Nový ceník",
        )
        assert rows == []


def test_structured_pricing_rejects_high_threshold_non_fee_rows():
    rows = _row_to_pricing_records(
        ["Název položky", "eKonto"],
        ["Kreditní obrat", "25 000 Kč měsíčně"],
        source_url="https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        source_file="cenik-pi.pdf",
        page=1,
        table_index=0,
        row_index=1,
        title="Nový ceník",
    )
    assert rows == []


def test_pricing_retriever_deterministic_jsonl(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "eKonto EXCLUSIVE",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "currency": "",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
            "source_file": "cenik-pi.pdf",
            "page": 4,
            "table_index": 0,
            "row_index": 1,
            "title": "Nový ceník",
            "section_title": "Nový ceník",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.9,
            "raw_cells": ["Vedení účtu", "zdarma"],
        }
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    docs = pricing_retriever.pricing_search("Kolik stojí vedení eKonta?", top_k=3, min_score=0.1)
    # default config path may be different; load directly to prove JSONL parser too
    loaded = pricing_retriever.load_pricing_rows(str(path))
    assert loaded[0]["product_name"] == "eKonto EXCLUSIVE"

    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení eKonta?", top_k=3, min_score=0.1)
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()
    assert docs
    assert docs[0].metadata["structured_pricing"] is True
    assert docs[0].metadata["chunk_type"] == "pricing_row"
    assert docs[0].metadata["fee_value"] == "zdarma"


def test_pricing_retriever_skips_low_confidence_rows(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    row = {
        "product_name": "eKonto",
        "fee_type": "Vedení účtu",
        "fee_value": "129 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        "source_file": "cenik-pi.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "Nový ceník",
        "section_title": "Nový ceník",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.69,
        "raw_cells": ["Vedení účtu", "129 Kč"],
    }
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení eKonta?", top_k=3, min_score=0.1)
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()
    assert docs == []

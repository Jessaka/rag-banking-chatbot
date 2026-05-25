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
    docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=3, min_score=0.1)
    # default config path may be different; load directly to prove JSONL parser too
    loaded = pricing_retriever.load_pricing_rows(str(path))
    assert loaded[0]["product_name"] == "eKonto EXCLUSIVE"

    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=3, min_score=0.1)
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
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=3, min_score=0.1)
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()
    assert len(docs) == 1
    assert docs[0].metadata["product_name"] == "Upozornění"
    assert docs[0].metadata["retrieval_debug"]["canonical_product"] == "ekonto_osobni"
    assert docs[0].metadata["retrieval_debug"]["fallback_used"] is False


# ---------------------------------------------------------------------------
# Primary account fee filter tests
# ---------------------------------------------------------------------------


def test_is_primary_account_fee_row_true_for_primary_fees():
    """Fee types that ARE primary account fees."""
    assert pricing_retriever.is_primary_account_fee_row({"fee_type": "1. Vedení jednoho běžného účtu", "product_name": "eKonto"})
    assert pricing_retriever.is_primary_account_fee_row({"fee_type": "1. Cena tarifu", "product_name": "AKTIVNÍ účet"})
    assert pricing_retriever.is_primary_account_fee_row({"fee_type": "Vedení běžného účtu", "product_name": "Běžný účet"})
    assert pricing_retriever.is_primary_account_fee_row({"fee_type": "Poplatek za vedení účtu", "product_name": "Účet"})
    assert pricing_retriever.is_primary_account_fee_row({"fee_type": "Měsíční poplatek za vedení", "product_name": "Účet"})


def test_is_primary_account_fee_row_false_for_secondary_fees():
    """Fee types that are NOT primary account fees."""
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "4. Vedení každé vedlejší měnové složky účtu 3)", "product_name": "AKTIVNÍ účet"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "1. Mobilní Elektronický klíč (MEK) pro přihlášení", "product_name": "AKTIVNÍ účet"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "Otevření a vedení běžného investičního účtu (BIU)", "product_name": "BIU"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "1.3. Zadání údajů elektronického Platebního příkazu", "product_name": "AKTIVNÍ účet"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "2. Správa služby", "product_name": "eKonto"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "", "product_name": "Test"})
    assert not pricing_retriever.is_primary_account_fee_row({"fee_type": "Vedení karty", "product_name": "Karta"})


def test_is_primary_account_fee_query_true():
    """Queries that SHOULD activate the primary filter."""
    assert pricing_retriever.is_primary_account_fee_query("Jaký je poplatek za vedení běžného účtu?")
    assert pricing_retriever.is_primary_account_fee_query("Kolik stojí vedení účtu?")
    assert pricing_retriever.is_primary_account_fee_query("Kolik stojí vedení eKonta?")  # OPRAVENO: nyní triggeruje na "vedení" samostatně
    assert pricing_retriever.is_primary_account_fee_query("Jaký je měsíční poplatek za eKonto?")
    assert pricing_retriever.is_primary_account_fee_query("Monthly account fee")
    assert pricing_retriever.is_primary_account_fee_query("Account maintenance fee")
    assert pricing_retriever.is_primary_account_fee_query("Kolik stojí účet?")
    assert pricing_retriever.is_primary_account_fee_query("Monthly fee")


def test_is_primary_account_fee_query_false():
    """Queries that MUST NOT activate the primary filter."""
    assert not pricing_retriever.is_primary_account_fee_query("Poplatek za výběr z bankomatu")
    assert not pricing_retriever.is_primary_account_fee_query("Úroková sazba hypotečního úvěru")
    assert not pricing_retriever.is_primary_account_fee_query("Kolik stojí kreditní karta?")
    assert not pricing_retriever.is_primary_account_fee_query("Jaký je poplatek za pojištění?")
    assert not pricing_retriever.is_primary_account_fee_query("Hello world")
    assert not pricing_retriever.is_primary_account_fee_query("Sjednání a správa služeb")  # "správa" ≠ "vedení"


def test_pricing_search_primary_filter_excludes_secondary_rows(tmp_path):
    """Query 'vedení běžného účtu' must return ONLY primary account fee rows."""
    path = tmp_path / "pricing_rows.jsonl"
    primary = {
        "product_name": "AKTIVNÍ účet",
        "fee_type": "1. Cena tarifu",
        "fee_value": "99 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "1. část Aktuálně nabízené produkty",
        "section_title": "Ceník",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    secondary_rows = [
        {
            "product_name": "AKTIVNÍ účet",
            "fee_type": "4. Vedení každé vedlejší měnové složky účtu 3)",
            "fee_value": "v ceně",
            "currency": "",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 2,
            "title": "1. část Aktuálně nabízené produkty",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.95,
        },
        {
            "product_name": "AKTIVNÍ účet",
            "fee_type": "1. Mobilní Elektronický klíč (MEK) pro přihlášení",
            "fee_value": "zdarma",
            "currency": "",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 3,
            "title": "1. část Aktuálně nabízené produkty",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.95,
        },
        {
            "product_name": "AKTIVNÍ účet",
            "fee_type": "Otevření a vedení běžného investičního účtu (BIU) v Kč",
            "fee_value": "1 000 Kč",
            "currency": "CZK",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 4,
            "title": "1. část Aktuálně nabízené produkty",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.95,
        },
        {
            "product_name": "AKTIVNÍ účet",
            "fee_type": "1.3. Zadání údajů elektronického Platebního příkazu",
            "fee_value": "100 Kč",
            "currency": "CZK",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 5,
            "title": "1. část Aktuálně nabízené produkty",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.95,
        },
    ]
    rows = [primary] + secondary_rows
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=10, min_score=0.1)
        assert len(docs) == 1, f"Očekáván 1 primary doc, ale je {len(docs)}"
        assert docs[0].metadata["fee_type"] == "1. Cena tarifu"
        # Verify retrieval debug
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") == "true"
        assert debug.get("primary_rows") == 1
        # Verify no secondary fee types leaked
        fee_types = [d.metadata["fee_type"] for d in docs]
        assert not any("vedlejší" in ft.lower() for ft in fee_types)
        assert not any("mobilní" in ft.lower() for ft in fee_types)
        assert not any("elektronický" in ft.lower() for ft in fee_types)
        assert not any("investiční" in ft.lower() for ft in fee_types)
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_pricing_search_primary_filter_blocks_general_fallback_for_canonical_product(tmp_path):
    """When no primary rows exist for a canonical product, return warning."""
    path = tmp_path / "pricing_rows.jsonl"
    non_primary = {
        "product_name": "AKTIVNÍ účet",
        "fee_type": "4. Vedení každé vedlejší měnové složky účtu 3)",
        "fee_value": "v ceně",
        "currency": "",
        "period": "",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "1. část Aktuálně nabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    path.write_text(json.dumps(non_primary, ensure_ascii=False), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=10, min_score=0.1)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upozornění"
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") is None
        assert debug.get("primary_fallback") == "true"
        assert debug.get("active_rows_count") == 1
        assert debug.get("active_results_count") is None
        assert debug.get("canonical_product") == "osobni_ucet"
        assert debug.get("fallback_used") is False
        assert debug.get("pricing_ranking_reason") == "no_active_primary_rows_for_canonical_product"
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_pricing_search_non_primary_query_ignores_primary_filter(tmp_path):
    """Queries like 'výběr z bankomatu' must NOT activate the primary filter."""
    path = tmp_path / "pricing_rows.jsonl"
    row = {
        "product_name": "eKonto",
        "fee_type": "Správa služby",
        "fee_value": "99 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "Ceník",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.90,
    }
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Poplatek za výběr z bankomatu", top_k=10, min_score=0.0)
        assert len(docs) == 1
        # Primary filter should NOT be active
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") is None
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_active_pricing_preferred_over_archived(tmp_path):
    """Active pricing rows are returned for normal queries; archived rows pass only
    when the query explicitly asks about historical/archived products."""
    path = tmp_path / "pricing_rows.jsonl"
    active = {
        "product_name": "eKonto",
        "fee_type": "Vedení účtu",
        "fee_value": "129 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "1. část Aktuálně nabízené produkty",
        "section_title": "Aktuálně nabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
        "raw_cells": ["Vedení účtu", "129 Kč"],
    }
    archived = {
        "product_name": "eKonto (již nenabízené)",
        "fee_type": "Vedení účtu",
        "fee_value": "99 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 2,
        "table_index": 0,
        "row_index": 1,
        "title": "2. část Již nenabízené produkty",
        "section_title": "Již nenabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.90,
        "raw_cells": ["Vedení účtu", "99 Kč"],
    }
    rows = [active, archived]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        # Normal query — should return only active
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=5, min_score=0.1)
        assert len(docs) == 1, f"Očekáván 1 aktivní doc, ale je {len(docs)}"
        assert docs[0].metadata["product_name"] == "eKonto"
        assert docs[0].metadata["title"] == "1. část Aktuálně nabízené produkty"
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("active_rows_count") == 1
        assert debug.get("archived_rows_count") == 1
        assert debug.get("active_results_count") == 1
        assert debug.get("archived_fallback_used") is None
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_active_primary_preferred_over_archived_primary(tmp_path):
    """When active primary rows exist, they must win even if archived primary has higher score."""
    path = tmp_path / "pricing_rows.jsonl"
    active_primary = {
        "product_name": "AKTIVNÍ účet",
        "fee_type": "1. Cena tarifu",
        "fee_value": "99 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "1. část Aktuálně nabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    archived_primary = {
        "product_name": "eKonto (archiv)",
        "fee_type": "1. Vedení jednoho běžného účtu",
        "fee_value": "250 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 2,
        "table_index": 0,
        "row_index": 1,
        "title": "2. část Již nenabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    rows = [active_primary, archived_primary]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=5, min_score=0.0)
        assert len(docs) == 1, f"Očekáván 1 active primary doc, ale je {len(docs)}"
        assert docs[0].metadata["product_name"] == "AKTIVNÍ účet"
        assert docs[0].metadata["fee_type"] == "1. Cena tarifu"
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") == "true"
        assert debug.get("archived_fallback_used") is None
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_archived_primary_not_used_for_canonical_product_when_no_active_primary(tmp_path):
    """Archived primary rows must not satisfy current canonical product queries."""
    path = tmp_path / "pricing_rows.jsonl"
    active_non_primary = {
        "product_name": "AKTIVNÍ účet",
        "fee_type": "4. Vedení každé vedlejší měnové složky účtu 3)",
        "fee_value": "v ceně",
        "currency": "",
        "period": "",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "1. část Aktuálně nabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    archived_primary = {
        "product_name": "eKonto (archiv)",
        "fee_type": "1. Vedení jednoho běžného účtu",
        "fee_value": "250 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 2,
        "table_index": 0,
        "row_index": 1,
        "title": "2. část Již nenabízené produkty",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    rows = [active_non_primary, archived_primary]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upozornění"
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") is None
        assert debug.get("archived_fallback_used") is None
        assert debug.get("canonical_product") == "osobni_ucet"
        assert debug.get("fallback_used") is False
        assert debug.get("pricing_ranking_reason") == "no_active_primary_rows_for_canonical_product"
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_service_config_fees_excluded_from_primary_query(tmp_path):
    """Query 'Kolik stojí vedení osobního eKonta?' must NOT return service/config rows.

    Rows like:
      - Správa služby
      - Telefonní notifikace
      - Doplňkové služby
      - Nastavení služby
      - RB klíč

    must be excluded when the primary account fee filter is active.
    """
    path = tmp_path / "pricing_rows.jsonl"
    primary = {
        "product_name": "eKonto",
        "fee_type": "Vedení účtu",
        "fee_value": "129 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/cenik.pdf",
        "source_file": "cenik.pdf",
        "page": 1,
        "table_index": 0,
        "row_index": 1,
        "title": "Ceník",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
    }
    service_rows = [
        {
            "product_name": "eKonto",
            "fee_type": "2. Správa služby",
            "fee_value": "50 Kč",
            "currency": "",
            "period": "měsíčně",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 2,
            "title": "Ceník",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.90,
        },
        {
            "product_name": "eKonto",
            "fee_type": "3. Telefonní bankovnictví",
            "fee_value": "zdarma",
            "currency": "",
            "period": "",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 3,
            "title": "Ceník",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.90,
        },
        {
            "product_name": "eKonto",
            "fee_type": "4. Doplňkové služby",
            "fee_value": "30 Kč",
            "currency": "",
            "period": "měsíčně",
            "conditions": "",
            "source_url": "https://www.rb.cz/cenik.pdf",
            "source_file": "cenik.pdf",
            "page": 1,
            "table_index": 0,
            "row_index": 4,
            "title": "Ceník",
            "category": "retail",
            "document_type": "pricing",
            "pricing_type": "account_fee",
            "confidence": 0.90,
        },
    ]
    rows = [primary] + service_rows
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        # This query now activates primary filter thanks to "vedení" trigger
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=10, min_score=0.1)
        assert len(docs) == 1, (
            f"Očekáván přesně 1 primary doc (Vedení účtu), "
            f"ale je {len(docs)}: {[d.metadata['fee_type'] for d in docs]}"
        )
        assert docs[0].metadata["fee_type"] == "Vedení účtu"
        # Verify retrieval debug
        debug = docs[0].metadata.get("retrieval_debug", {})
        assert debug.get("primary_account_fee_filter") == "true"
        assert debug.get("primary_rows") == 1
        assert "primary_fee_reason" in debug
        # Ve primary_fee_reason musí být zmínka o excludovaných service rows
        excluded_ft = debug.get("primary_fee_reason", "")
        assert "sprava" in excluded_ft or "excluded" in excluded_ft
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_ekonto_prefers_2026_active_over_2018_2020_archived(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "250 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2018.pdf",
            "title": "Ceník 2018",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.99,
            "document_year": 2018,
        },
        {
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "400 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2020.pdf",
            "title": "Ceník 2020",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.99,
            "document_year": 2020,
        },
        {
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "129 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2026.pdf",
            "title": "Ceník 2026 Aktuálně nabízené produkty",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.90,
            "document_year": 2026,
            "is_active": True,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=5, min_score=0.0)
        assert docs
        assert all(d.metadata["document_year"] == 2026 for d in docs)
        assert all(d.metadata["is_active"] is True for d in docs)
        assert {d.metadata["fee_value"] for d in docs} == {"129 Kč"}
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["selected_document_year"] == 2026
        assert debug["archived_rows_count"] == 2
        assert len(debug["rejected_archived_rows"]) == 2
        assert debug["selected_pricing_rows"][0]["document_year"] == 2026
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_current_account_fee_does_not_mix_archived_with_active(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "Běžný účet mimo tarify",
            "fee_type": "1. Vedení jednoho běžného účtu",
            "fee_value": "500 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2018.pdf",
            "title": "Již nenabízené produkty 2018",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.99,
            "document_year": 2018,
        },
        {
            "product_name": "CHYTRÝ účet",
            "fee_type": "1. Cena tarifu",
            "fee_value": "0 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2026.pdf",
            "title": "Aktuální ceník 2026",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.90,
            "document_year": 2026,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "CHYTRÝ účet"
        assert docs[0].metadata["document_year"] == 2026
        assert "2018" not in docs[0].metadata["source_file"]
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_archived_rows_used_only_when_no_active_data(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    row = {
        "product_name": "eKonto archiv",
        "fee_type": "Vedení účtu",
        "fee_value": "250 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "source_file": "cenik-pi-2018.pdf",
        "title": "Již nenabízené produkty 2018",
        "category": "retail",
        "pricing_type": "account_fee",
        "confidence": 0.95,
        "document_year": 2018,
    }
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upozornění"
        assert "Nepodařilo se najít jednoznačný aktuální ceník" in docs[0].metadata["fee_type"]
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "ekonto_osobni"
        assert debug["fallback_used"] is False
        assert debug["pricing_ranking_reason"] == "no_active_rows_for_canonical_product"
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_duplicate_current_price_rows_are_deduped(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    row = {
        "product_name": "eKonto",
        "fee_type": "Vedení účtu",
        "fee_value": "129 Kč",
        "currency": "CZK",
        "period": "měsíčně",
        "source_file": "cenik-pi-2026.pdf",
        "title": "Aktuální ceník 2026",
        "category": "retail",
        "pricing_type": "account_fee",
        "confidence": 0.95,
        "document_year": 2026,
    }
    rows = [row, {**row, "page": 2, "row_index": 99}]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["fee_value"] == "129 Kč"
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_generic_account_fee_query_does_not_return_500_250_400_without_current_tariff(tmp_path):
    """Regression for mixed/orphan account fee rows from old ceníky.

    Generic query must not return historical 500/250/400 Kč rows when a current
    active tariff row exists. It should return one well-mapped current product.
    """
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "eKonto Základní cena",
            "fee_type": "1. Vedení jednoho běžného účtu",
            "fee_value": "500 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "pricing_cenik-pi-2_55d9608ef7.pdf",
            "title": "Starý ceník bez data",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 1.0,
        },
        {
            "product_name": "eKonto Výhody Prémium",
            "fee_type": "1. Vedení jednoho běžného účtu",
            "fee_value": "250 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "pricing_cenik-pi-2_55d9608ef7.pdf",
            "title": "Starý ceník bez data",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 1.0,
        },
        {
            "product_name": "eKonto Základní cena",
            "fee_type": "1. Vedení jednoho běžného účtu",
            "fee_value": "400 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2020.pdf",
            "title": "Ceník 2020",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 1.0,
            "document_year": 2020,
        },
        {
            "product_name": "Základní platební účet",
            "fee_type": "1. Vedení účtu",
            "fee_value": "zdarma",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-zpu-2026.pdf",
            "title": "Aktuální ceník 2026",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Základní platební účet"
        assert docs[0].metadata["fee_value"] == "zdarma"
        assert docs[0].metadata["document_year"] == 2026
        assert docs[0].metadata["fee_value"] not in {"500 Kč", "250 Kč", "400 Kč"}
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["selected_document_year"] == 2026
        assert len(debug["rejected_archived_rows"]) >= 3
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_ambiguous_ekonto_query_returns_clarification_not_pricing(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "Základní platební účet",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-zpu-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
        {
            "product_name": "eKonto archiv",
            "fee_type": "Vedení účtu",
            "fee_value": "250 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2020.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2020,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení eKonta?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upřesnění"
        assert "osobní eKonto" in docs[0].metadata["fee_type"]
        assert "podnikatelské eKonto" in docs[0].metadata["fee_type"]
        assert docs[0].metadata["fee_value"] == ""
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "ekonto_ambiguous"
        assert debug["product_match_confidence"] >= 0.75
        assert debug["matched_product_rows"] == 0
        assert debug["clarification_required"] is True
        assert debug["fallback_used"] is False
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_business_account_query_does_not_fallback_to_personal_account(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "Základní platební účet",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-zpu-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        }
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí podnikatelský účet?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upozornění"
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "podnikatelsky_ucet"
        assert debug["matched_product_rows"] == 0
        assert debug["rejected_cross_product_rows"][0]["product_name"] == "Základní platební účet"
        assert debug["fallback_used"] is False
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_corporate_account_query_does_not_fallback_to_personal_account(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "Osobní účet",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        }
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí firemní účet?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Upozornění"
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "firemni_ucet"
        assert debug["matched_product_rows"] == 0
        assert debug["fallback_used"] is False
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_basic_account_query_can_use_personal_account_fallback(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "Základní platební účet",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-zpu-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
        {
            "product_name": "Podnikatelské eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "129 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-podnikatele-2026.pdf",
            "category": "corporate",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Jaký je poplatek za vedení běžného účtu?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Základní platební účet"
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "osobni_ucet"
        assert debug["fallback_used"] is False
        assert all(r["product_name"] != "Podnikatelské eKonto" for r in debug["selected_pricing_rows"])
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_personal_ekonto_does_not_use_business_ekonto_rows(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "129 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
        {
            "product_name": "Podnikatelské eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "500 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-fop-2026.pdf",
            "category": "corporate",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení osobního eKonta?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "eKonto"
        assert docs[0].metadata["fee_value"] == "129 Kč"
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "ekonto_osobni"
        assert docs[0].metadata["pricing_product_segment"] == "personal"
        assert all(r["product_name"] != "Podnikatelské eKonto" for r in debug["selected_pricing_rows"])
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()


def test_business_ekonto_does_not_use_personal_ekonto_rows(tmp_path):
    path = tmp_path / "pricing_rows.jsonl"
    rows = [
        {
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "129 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-pi-2026.pdf",
            "category": "retail",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
        {
            "product_name": "Podnikatelské eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "500 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "source_file": "cenik-fop-2026.pdf",
            "category": "corporate",
            "pricing_type": "account_fee",
            "confidence": 0.95,
            "document_year": 2026,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    try:
        docs = pricing_retriever.pricing_search("Kolik stojí vedení podnikatelského eKonta?", top_k=5, min_score=0.0)
        assert len(docs) == 1
        assert docs[0].metadata["product_name"] == "Podnikatelské eKonto"
        assert docs[0].metadata["fee_value"] == "500 Kč"
        debug = docs[0].metadata["retrieval_debug"]
        assert debug["canonical_product"] == "ekonto_podnikatelske"
        assert docs[0].metadata["pricing_product_segment"] == "business"
        assert all(r["product_name"] != "eKonto" for r in debug["selected_pricing_rows"])
    finally:
        pricing_retriever.config.PRICING_ROWS_PATH = original
        pricing_retriever.load_pricing_rows.cache_clear()

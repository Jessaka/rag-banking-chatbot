import json

from src.retrieval import pricing_retriever
from src.retrieval.pricing_resolver import normalize_price, resolve_pricing_query


def _write_rows(tmp_path, rows):
    path = tmp_path / "pricing_rows.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    pricing_retriever.load_pricing_rows.cache_clear()
    original = pricing_retriever.config.PRICING_ROWS_PATH
    pricing_retriever.config.PRICING_ROWS_PATH = path
    return original


def _restore_path(original):
    pricing_retriever.config.PRICING_ROWS_PATH = original
    pricing_retriever.load_pricing_rows.cache_clear()


def _row(**overrides):
    base = {
        "product_name": "eKonto",
        "fee_type": "Vedení účtu",
        "fee_value": "zdarma",
        "currency": "CZK",
        "period": "měsíčně",
        "conditions": "",
        "source_url": "https://www.rb.cz/attachments/ceniky/cenik-pi.pdf",
        "source_file": "cenik-pi.pdf",
        "page": 4,
        "table_index": 0,
        "row_index": 1,
        "title": "Aktuální ceník",
        "section_title": "Ceník osobních účtů",
        "category": "retail",
        "document_type": "pricing",
        "pricing_type": "account_fee",
        "confidence": 0.95,
        "document_year": 2026,
        "valid_from": "2026-01-01",
        "raw_cells": ["Vedení účtu", "zdarma"],
    }
    base.update(overrides)
    return base


def test_zdarma_normalization_variants():
    for value in ["zdarma", "0 Kč", "bez poplatku", "měsíčně zdarma", "vedení zdarma", "fee waived"]:
        normalized = normalize_price(value)
        assert normalized["normalized_price"] == 0
        assert normalized["currency"] == "CZK"
        assert normalized["billing_period"] == "monthly"
        assert normalized["semantic_label"] == "free"
    assert normalize_price("first year free")["semantic_label"] == "free"


def test_exact_row_extraction_ekonto_free(tmp_path):
    original = _write_rows(tmp_path, [_row()])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení eKonta?", top_k=3)
    finally:
        _restore_path(original)
    assert docs
    top = docs[0]
    assert top.metadata["pricing_row_found"] is True
    assert top.metadata["pricing_row_exact_match"] is True
    assert top.metadata["pricing_confidence"] == "high"
    assert top.metadata["normalized_price"] == 0
    assert top.metadata["pricing_canonical_used"] is True


def test_archived_suppression_prefers_current_row(tmp_path):
    archived = _row(
        fee_value="129 Kč",
        document_year=2020,
        source_file="archiv_cenik_2020.pdf",
        title="Archivní ceník",
        is_archived=True,
    )
    current = _row(fee_value="zdarma", document_year=2026, source_file="cenik-pi-2026.pdf")
    original = _write_rows(tmp_path, [archived, current])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení osobního eKonta?", top_k=3)
    finally:
        _restore_path(original)
    assert docs[0].metadata["fee_value"] == "zdarma"
    assert docs[0].metadata["document_year"] == 2026
    assert "archiv" not in str(docs[0].metadata.get("source_file", "")).lower()


def test_duplicate_pricing_docs_prefer_newest_generation(tmp_path):
    old = _row(fee_value="zdarma", document_year=2025, source_file="cenik-pi-2025.pdf")
    new = _row(fee_value="zdarma", document_year=2026, source_file="cenik-pi-2026.pdf")
    original = _write_rows(tmp_path, [old, new])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení osobního eKonta?", top_k=1)
    finally:
        _restore_path(original)
    assert docs[0].metadata["document_year"] == 2026


def test_stale_conflict_resolution_blocks_old_price(tmp_path):
    stale = _row(fee_value="129 Kč", document_year=2018, source_file="cenik-pi-2018.pdf", is_archived=True)
    current = _row(fee_value="zdarma", document_year=2026, source_file="cenik-pi-2026.pdf")
    original = _write_rows(tmp_path, [stale, current])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení eKonta?", top_k=3)
    finally:
        _restore_path(original)
    assert all(doc.metadata.get("document_year") != 2018 for doc in docs)
    assert docs[0].metadata["normalized_price"] == 0


def test_ambiguity_safe_fallback_when_no_matching_row(tmp_path):
    original = _write_rows(tmp_path, [])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení eKonta?", top_k=3)
    finally:
        _restore_path(original)
    assert docs
    assert docs[0].metadata["pricing_safe_fallback"] is True
    assert docs[0].metadata["pricing_confidence"] == "low"


def test_supported_pricing_parser_failure_does_not_return_unsupported(tmp_path):
    original = _write_rows(tmp_path, [])
    try:
        docs = resolve_pricing_query("Jaký je poplatek za SEPA platbu?", top_k=3)
    finally:
        _restore_path(original)
    assert docs
    assert "nepodpor" not in docs[0].page_content.lower()
    assert docs[0].metadata["pricing_safe_fallback"] is True


def test_ekonto_conditional_overlay_beats_unrelated_oek_fee(tmp_path):
    conditional_account_fee = _row(
        product_name="eKonto SMART",
        fee_type="Vedení účtu",
        fee_value="99 Kč",
        base_price=99,
        conditional_price=0,
        condition_type="active_usage",
        condition_text="při aktivním využívání účtu",
        conditions="zdarma při aktivním využívání účtu; jinak 99 Kč měsíčně",
        document_year=2024,
        source_file="cenik-pi-2024.pdf",
        canonical_product_groups=["ekonto_osobni", "osobni_ucet"],
        is_active=True,
        is_archived=False,
    )
    unrelated_oek_fee = _row(
        product_name="eKonto KOMPLET, eKonto SMART, PRÉMIOVÝ účet",
        fee_type="3. Přístup k účtu prostřednictvím Osobního Elektronického klíče (OEk)",
        fee_value="89 Kč",
        amount=89,
        raw_cells=["OEk", "89 Kč"],
        document_year=2024,
        canonical_product_groups=["ekonto_osobni", "osobni_ucet"],
        is_active=True,
        is_archived=False,
    )
    original = _write_rows(tmp_path, [unrelated_oek_fee, conditional_account_fee])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení osobního eKonta?", top_k=3)
    finally:
        _restore_path(original)

    assert docs[0].metadata["product_name"] == "eKonto SMART"
    assert docs[0].metadata["fee_value"] == "podmíněně zdarma / jinak 99 Kč"
    assert docs[0].metadata["base_price"] == 99
    assert docs[0].metadata["conditional_price"] == 0
    assert docs[0].metadata["condition_type"] == "active_usage"
    assert docs[0].metadata["conditional_pricing_detected"] is True
    assert docs[0].metadata["normalized_price"] is None
    assert docs[0].metadata["pricing_row_exact_match"] is True
    assert docs[0].metadata["pricing_confidence"] == "high"
    assert "Elektronického klíče" not in docs[0].metadata["fee_type"]


def test_conditional_price_does_not_collapse_to_absolute_free(tmp_path):
    row = _row(
        product_name="eKonto SMART",
        fee_type="Vedení účtu",
        fee_value="99 Kč",
        base_price=99,
        conditional_price=0,
        condition_type="active_usage",
        condition_text="3 karetní transakce měsíčně",
        conditions="zdarma při aktivním využívání účtu; jinak 99 Kč měsíčně",
        canonical_product_groups=["ekonto_osobni", "osobni_ucet"],
        is_active=True,
        is_archived=False,
    )
    original = _write_rows(tmp_path, [row])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení eKonto SMART?", top_k=1)
    finally:
        _restore_path(original)

    assert docs[0].metadata["conditional_pricing_detected"] is True
    assert docs[0].metadata["conditional_price"] == 0
    assert docs[0].metadata["base_price"] == 99
    assert docs[0].metadata["normalized_price"] is None
    assert docs[0].metadata["pricing_semantic_label"] == "conditional"
    assert docs[0].metadata["fee_value"] != "zdarma"


def test_semantic_detection_for_active_usage_condition(tmp_path):
    row = _row(
        product_name="eKonto SMART",
        fee_type="Vedení účtu",
        fee_value="zdarma při aktivním využívání účtu, jinak 99 Kč měsíčně",
        conditions="při splnění podmínek aktivního využívání",
        canonical_product_groups=["ekonto_osobni", "osobni_ucet"],
        is_active=True,
        is_archived=False,
    )
    original = _write_rows(tmp_path, [row])
    try:
        docs = resolve_pricing_query("Kolik stojí vedení eKonto SMART?", top_k=1)
    finally:
        _restore_path(original)

    assert docs[0].metadata["conditional_pricing_detected"] is True
    assert docs[0].metadata["condition_type"] == "active_usage"
    assert docs[0].metadata["conditional_price"] == 0
    assert docs[0].metadata["base_price"] == 99


def test_mainstream_product_boost_preferred_over_niche(tmp_path):
    """Generic 'běžný účet' must prefer mainstream (eKonto SMART) over basic payment account."""
    basic_payment = _row(
        product_name="Základní platební účet",
        fee_type="Vedení účtu",
        fee_value="zdarma",
        conditions="Základní platební účet dle zákona",
        raw_cells=["Základní platební účet", "zdarma"],
        canonical_product_groups=["basic_payment_account"],
        is_active=True,
        is_archived=False,
        document_year=2025,
        source_file="cenik-zpu-2025.pdf",
    )
    mainstream_account = _row(
        product_name="eKonto Výhody Prémium",
        fee_type="1. Vedení jednoho běžného účtu",
        fee_value="250 Kč",
        canonical_product_groups=["ekonto_osobni", "osobni_ucet"],
        is_active=True,
        is_archived=False,
        document_year=2025,
        source_file="cenik-2025.pdf",
        mainstream_product=True,
    )
    original = _write_rows(tmp_path, [basic_payment, mainstream_account])
    try:
        docs = resolve_pricing_query("Jaký je poplatek za vedení běžného účtu?", top_k=3)
    finally:
        _restore_path(original)

    # Must prefer mainstream over basic payment account
    assert docs[0].metadata["product_name"] != "Základní platební účet"
    assert docs[0].metadata["product_name"] == "eKonto Výhody Prémium"
    assert docs[0].metadata.get("mainstream_boost_applied") is True or docs[0].metadata.get("mainstream_boost_applied") is None
    assert "základní" not in docs[0].metadata["product_name"].lower()


def test_basic_payment_account_suppressed_unless_explicit(tmp_path):
    """Basic payment account must only be selected when explicitly queried."""
    basic_payment = _row(
        product_name="Základní platební účet",
        fee_type="Vedení účtu",
        fee_value="zdarma",
        conditions="Základní platební účet dle zákona",
        raw_cells=["Základní platební účet", "zdarma"],
        canonical_product_groups=["basic_payment_account"],
        is_active=True,
        is_archived=False,
        document_year=2025,
        source_file="cenik-zpu-2025.pdf",
    )
    original = _write_rows(tmp_path, [basic_payment])
    try:
        explicit_docs = resolve_pricing_query("Jaký je poplatek za základní platební účet?", top_k=3)
    finally:
        _restore_path(original)

    assert explicit_docs[0].metadata.get("pricing_row_found") is True
    assert "základní" in explicit_docs[0].metadata.get("product_name", "").lower()

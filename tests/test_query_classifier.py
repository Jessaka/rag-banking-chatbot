from langchain_core.documents import Document

from src.retrieval.query_classifier import classify_query, detect_chunk_quality, expand_query, freshness_priority, is_archived_doc, is_corporate_doc, is_personal_retail_doc, source_priority
from src.generation.prompts import format_context


def test_retail_account_pricing_prefers_osobni_and_penalizes_firmy():
    profile = classify_query("Jaký je poplatek za vedení běžného účtu?")
    assert "pricing" in profile.labels
    assert "retail_banking" in profile.labels
    assert "/osobni/" in profile.preferred_url_contains
    assert "/firmy/" in profile.penalized_url_contains

    retail_doc = Document(
        page_content="Běžný účet eKonto vedení účtu zdarma poplatek Kč",
        metadata={"source_url": "https://www.rb.cz/osobni/ucty/ekonto", "category": "accounts", "document_type": "pricing", "chunk_type": "pricing"},
    )
    corp_doc = Document(
        page_content="Firemní účet corporate ceník poplatek Kč",
        metadata={"source_url": "https://www.rb.cz/firmy/produkty-a-sluzby/cenik", "category": "business", "document_type": "pricing", "chunk_type": "pricing"},
    )
    retail_score, _ = source_priority(retail_doc, profile)
    corp_score, reasons = source_priority(corp_doc, profile)
    assert retail_score > corp_score
    assert any("penalized" in reason for reason in reasons)


def test_eval_queries_classification():
    cases = {
        "Jaký je poplatek za vedení běžného účtu?": {"pricing", "retail_banking"},
        "Kolik stojí AKTIVNÍ účet?": {"pricing", "retail_banking"},
        "Jak změnit limit karty?": {"support", "cards"},
        "Jaké jsou poplatky za výběr v zahraničí?": {"pricing", "cards"},
    }
    for query, expected in cases.items():
        assert expected.issubset(classify_query(query).labels)


def test_credit_card_catalog_queries_are_classified_and_expanded():
    for query in ["Jaké máte kreditky?", "Jaké kreditní karty nabízíte?", "Jaké jsou druhy kreditek?"]:
        profile = classify_query(query)
        assert {"cards", "credit_card", "credit_card_catalog", "catalog_intent"}.issubset(profile.labels)
        expanded = expand_query(query, profile).lower()
        assert "kreditní karta" in expanded
        assert "splátková karta" in expanded


def test_credit_card_catalog_source_priority_boosts_credit_sources():
    profile = classify_query("Jaké máte kreditky?")
    credit_doc = Document(
        page_content="Kreditní karta EASY Kreditní karta STYLE Mastercard Visa kreditní karta",
        metadata={"source_url": "https://www.rb.cz/osobni/kreditni-karty", "category": "cards", "chunk_type": "section_text"},
    )
    generic_doc = Document(
        page_content="Debetní karty k osobním účtům",
        metadata={"source_url": "https://www.rb.cz/osobni/debetni-karty", "category": "cards", "chunk_type": "section_text"},
    )
    credit_score, reasons = source_priority(credit_doc, profile)
    generic_score, _ = source_priority(generic_doc, profile)
    assert credit_score > generic_score
    assert any("boosted_product_group=kreditni_karta" in reason for reason in reasons)


def test_payment_card_overview_query_is_supported_domain_not_faq_only():
    query = "Jaké typy platebních karet nabízíte?"
    profile = classify_query(query)
    assert {"cards", "catalog_intent", "card_overview", "product_overview", "supported_domain"}.issubset(profile.labels)
    expanded = expand_query(query, profile).lower()
    assert "platební karty" in expanded
    assert "debetní karta" in expanded
    assert "kreditní karta" in expanded

    card_doc = Document(
        page_content="Platební karty Debetní karta Kreditní karta Mastercard Visa virtuální karta",
        metadata={"source_url": "https://www.rb.cz/osobni/karty", "category": "cards", "chunk_type": "section_text"},
    )
    off_domain = Document(
        page_content="UNIQA pojišťovna cestovní pojištění",
        metadata={"source_url": "https://www.rb.cz/pojisteni", "category": "insurance", "chunk_type": "section_text"},
    )
    card_score, reasons = source_priority(card_doc, profile)
    off_score, _ = source_priority(off_domain, profile)
    assert card_score > off_score
    assert any("card overview" in reason for reason in reasons)


def test_bezny_ucet_is_personal_retail_without_business_terms():
    profile = classify_query("Jaký je poplatek za vedení běžného účtu?")
    assert "personal_retail_account" in profile.labels
    assert "business_account" not in profile.labels
    assert "entrepreneur_account" not in profile.labels


def test_business_account_terms_are_not_personal_retail():
    profile = classify_query("Jaký je poplatek za podnikatelský běžný účet pro OSVČ?")
    assert "business_account" in profile.labels
    assert "entrepreneur_account" in profile.labels
    assert "personal_retail_account" not in profile.labels


def test_personal_retail_excludes_fop_corp_business_sources():
    bad_docs = [
        Document(page_content="Podnikatelské eKonto paušální poplatek", metadata={"source_url": "https://www.rb.cz/podnikatele/ucty", "file_name": "pricing_ceniky-fop-porovnani-042018.pdf", "category": "corporate"}),
        Document(page_content="Firemní účet corporate poplatek", metadata={"source_url": "https://www.rb.cz/firmy/cenik", "file_name": "cenik-corp-1.pdf", "category": "corporate"}),
    ]
    for doc in bad_docs:
        assert is_corporate_doc(doc)
        assert not is_personal_retail_doc(doc)

    good_doc = Document(page_content="eKonto běžný účet vedení účtu zdarma", metadata={"source_url": "https://www.rb.cz/osobni/ucty/ekonto", "file_name": "cenik-pi-1.pdf", "category": "retail", "document_type": "pricing"})
    assert is_personal_retail_doc(good_doc)


def test_bad_pdf_extraction_detection():
    bad = "z V e c h n p r o v U S D " * 20
    assert detect_chunk_quality(bad) == "bad_pdf_extraction"


def test_archived_pricing_is_demoted_for_current_personal_account_query():
    profile = classify_query("Jaký je poplatek za vedení běžného účtu?")
    archived = Document(
        page_content="Již nenabízené produkty eKonto běžný účet poplatek",
        metadata={"title": "2. část Již nenabízené produkty", "category": "retail", "document_type": "pricing", "chunk_type": "pricing", "pricing_type": "account_fee", "is_archived": True},
    )
    active = Document(
        page_content="Aktuálně nabízené produkty eKonto běžný účet poplatek",
        metadata={"title": "1. část Aktuálně nabízené produkty", "category": "retail", "document_type": "pricing", "chunk_type": "pricing", "pricing_type": "account_fee", "is_archived": False, "document_year": 2026},
    )
    archived_score, archived_penalty, _ = freshness_priority(archived, profile)
    active_score, active_penalty, _ = freshness_priority(active, profile)
    assert is_archived_doc(archived)
    assert not is_archived_doc(active)
    assert archived_penalty <= -0.5
    assert active_score > 0
    assert active_score + active_penalty > archived_score + archived_penalty


def test_ekonto_query_prefers_pricing_row_over_full_table():
    profile = classify_query("Kolik stojí vedení eKonta?")
    expanded = expand_query("Kolik stojí vedení eKonta?", profile)
    assert "ekonto" in expanded.lower()
    assert "ekonta" in expanded.lower()
    assert "vedení účtu" in expanded.lower()
    assert "poplatek" in expanded.lower()
    assert "cena" in expanded.lower()
    row = Document(
        page_content="Table: Sazebník\nSekce: Běžné účty\nProdukt: eKonto\nVedení účtu: zdarma",
        metadata={
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "category": "retail",
            "pricing_type": "account_fee",
            "product_name": "eKonto",
            "fee_type": "Vedení účtu",
            "fee_value": "zdarma",
            "chunk_quality": "ok",
        },
    )
    table = Document(
        page_content="| Produkt | Vedení účtu |\n| --- | --- |\n| eKonto | zdarma |\n| Jiný účet | 99 Kč |",
        metadata={"chunk_type": "table", "document_type": "pricing", "category": "retail", "pricing_type": "account_fee"},
    )
    row_score, row_reasons = source_priority(row, profile)
    table_score, _ = source_priority(table, profile)
    assert row_score > table_score + 0.3
    assert "atomic pricing_row preferred" in row_reasons


def test_bad_table_row_is_penalized_and_full_table_context_filtered():
    profile = classify_query("Kolik stojí vedení eKonta?")
    bad_row = Document(
        page_content="Produkt: e K o n t o V e d e n í ú č t u: z d a r m a",
        metadata={"chunk_type": "pricing_row", "document_type": "pricing", "category": "retail", "chunk_quality": "bad_table_row"},
    )
    good_row = Document(
        page_content="Produkt: eKonto\nVedení účtu: zdarma",
        metadata={"chunk_type": "pricing_row", "document_type": "pricing", "category": "retail", "pricing_type": "account_fee", "fee_value": "zdarma"},
    )
    bad_score, bad_reasons = source_priority(bad_row, profile)
    good_score, _ = source_priority(good_row, profile)
    assert bad_score < good_score
    assert "bad_table_row penalty" in bad_reasons

    table = Document(page_content="| Produkt | Vedení účtu |\n| eKonto | zdarma |", metadata={"chunk_type": "table", "title": "Full table"})
    context = format_context([good_row, table])
    assert "Produkt: eKonto" in context
    assert "| Produkt |" not in context

import pytest
from src.retrieval.query_classifier import classify_query

@pytest.mark.parametrize("query", [
    "Jaké kreditní karty banka nabízí?",
    "Jaké osobní účty banka nabízí?",
    "Jaké typy úvěrů banka nabízí?",
    "Jaké hypotéky banka nabízí?",
])
def test_catalog_product_overview_no_faq_support(query):
    profile = classify_query(query)
    # Očekáváme, že dotaz má labely catalog_intent a product_overview
    assert "catalog_intent" in profile.labels
    assert "product_overview" in profile.labels
    # Po úpravě by neměl mít faq ani support
    assert "faq" not in profile.labels
    assert "support" not in profile.labels
    # Preferred document types must be set to the explicit list
    expected = {"product_page", "account_product", "credit_card", "mortgage_product", "product_catalog"}
    assert set(profile.preferred_document_types) == expected

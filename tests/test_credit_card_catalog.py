from langchain_core.documents import Document

from src.generation.chain import _format_credit_card_catalog_answer


def test_credit_card_catalog_answer_lists_products_and_not_unsupported():
    docs = [
        Document(
            page_content=(
                "Kreditní karty Raiffeisenbank Kreditní karta EASY "
                "Kreditní karta STYLE Kreditní karta RB PREMIUM Kreditní karta Visa Gold"
            ),
            metadata={"source_url": "https://www.rb.cz/osobni/kreditni-karty", "retrieval_route": "credit_card_catalog"},
        )
    ]
    answer = _format_credit_card_catalog_answer(docs)
    assert answer
    lowered = answer.lower()
    assert "kreditní karta" in lowered
    assert any(product in answer for product in ["Kreditní karta EASY", "Kreditní karta STYLE", "Kreditní karta RB PREMIUM", "Kreditní karta Visa Gold"])
    assert "nenalezl" not in lowered
    assert "nevím" not in lowered

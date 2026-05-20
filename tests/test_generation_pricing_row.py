from langchain_core.documents import Document

from src.generation.chain import BankingRAGChain, extract_structured_pricing_answer, normalize_product_name


class FakeRetriever:
    def __init__(self, docs):
        self.docs = docs

    def invoke(self, query):
        return self.docs


class FailingLLM:
    called = False

    def invoke(self, messages):
        self.called = True
        return "Tuto informaci jsem v dostupných dokumentech nenalezl. Prosím kontaktujte podporu."


def _pricing_row_doc():
    return Document(
        page_content="Produkt: eKonto EXCLUSIVE\nVedení účtu: zdarma",
        metadata={
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "product_name": "eKonto EXCLUSIVE",
            "fee_type": "Poplatek za vedení účtu",
            "fee_value": "zdarma",
            "period": "",
            "structured_pricing": True,
            "confidence": 0.95,
            "chunk_quality": "ok",
            "source_url": "https://www.rb.cz/attachments/ceniky/cenik-pi-01042018.pdf",
            "file_name": "cenik-pi-01042018.pdf",
            "page": 4,
            "rerank_score": 0.42,
        },
    )


def test_extract_structured_pricing_answer_from_metadata():
    parsed = extract_structured_pricing_answer(_pricing_row_doc())
    assert parsed["product_name"] == "eKonto EXCLUSIVE"
    assert parsed["fee_type"] == "Poplatek za vedení účtu"
    assert parsed["fee_value"] == "zdarma"


def test_extract_structured_pricing_answer_fee_regex_fallback():
    doc = _pricing_row_doc()
    doc.metadata["fee_value"] = ""
    doc.page_content = "Produkt: eKonto\nVedení účtu: 129 Kč měsíčně"
    parsed = extract_structured_pricing_answer(doc)
    assert parsed["fee_value"] == "129 Kč měsíčně"


def test_pricing_row_direct_answer_skips_llm_fallback():
    llm = FailingLLM()
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = llm
    chain._retriever = FakeRetriever([_pricing_row_doc()])

    result = chain.ask("Kolik stojí vedení eKonta?")

    assert result["answer_strategy"] == "pricing_row_direct"
    assert result["answer_confidence"] == "high"
    assert "eKonto EXCLUSIVE:" in result["answer"]
    assert "* poplatek za vedení účtu: zdarma" in result["answer"]
    assert "Zdroj:" in result["answer"]
    assert "Produkt:" not in result["answer"]
    assert "rerank_score" not in result["answer"]
    assert "chunk_id" not in result["answer"]
    assert "nenalezl" not in result["answer"].lower()
    assert "kontaktujte" not in result["answer"].lower()
    assert llm.called is False
    assert result["retrieval_debug"][0]["answer_strategy"] == "pricing_row_direct"
    assert result["sources"] == [{"title": "Ceník Raiffeisenbank", "page": 4, "url": "https://www.rb.cz/attachments/ceniky/cenik-pi-01042018.pdf"}]


def test_structured_pricing_answer_groups_max_three_products():
    docs = []
    for idx, product in enumerate(["eKonto Základní", "eKonto Výhody Prémium", "eKonto SMART", "eKonto EXTRA"], start=1):
        docs.append(Document(
            page_content=f"Produkt: {product}\nVedení účtu: {idx * 100} Kč měsíčně",
            metadata={
                "chunk_type": "pricing_row",
                "document_type": "pricing",
                "structured_pricing": True,
                "confidence": 0.9,
                "product_name": product,
                "fee_type": "Vedení účtu",
                "fee_value": f"{idx * 100} Kč",
                "period": "měsíčně",
                "chunk_quality": "ok",
                "source_url": "https://www.rb.cz/cenik.pdf",
                "source_file": "cenik.pdf",
                "title": "Ceník Raiffeisenbank",
                "page": idx,
                "rerank_score": 1.0,
            },
        ))
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever(docs)
    result = chain.ask("Kolik stojí vedení eKonta?")
    assert result["answer"].count("eKonto") == 3
    assert "eKonto EXTRA" not in result["answer"]
    assert "* vedení účtu: 100 Kč měsíčně" in result["answer"]
    assert "\\n" not in result["answer"]


def test_normalize_product_name_strips_suffixes():
    # Suffixes stripped
    assert normalize_product_name("eKonto Základní cena") == "eKonto Základní"
    assert normalize_product_name("eKonto EXCLUSIVE") == "eKonto EXCLUSIVE"
    assert normalize_product_name("Podnikatelské eKonto - Základní cena") == "Podnikatelské eKonto - Základní"
    assert normalize_product_name("AKTIVNÍ účet") == "AKTIVNÍ účet"  # preserved
    # Preserved names
    assert normalize_product_name("eKonto SMART") == "eKonto SMART"
    assert normalize_product_name("eKonto Výhody Prémium") == "eKonto Výhody Prémium"
    assert normalize_product_name("eKonto KOMPLET") == "eKonto KOMPLET"
    # Empty/edge
    assert normalize_product_name("") == ""
    assert normalize_product_name(None) is None

from langchain_core.documents import Document

from src.generation.chain import BankingRAGChain, extract_structured_pricing_answer, normalize_product_name


class FakeRetriever:
    def __init__(self, docs):
        self.docs = docs

    def invoke(self, query):
        return self.docs


class FailingRetriever:
    def invoke(self, query):
        raise AssertionError("identity route must not call retrieval")


class FailingLLM:
    called = False

    def invoke(self, messages):
        self.called = True
        return "Tuto informaci jsem v dostupných dokumentech nenalezl. Prosím kontaktujte podporu."


def test_identity_route_skips_retrieval_and_sources():
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = FailingLLM()
    chain._retriever = FailingRetriever()

    result = chain.ask("kdo jste")

    answer_lower = result["answer"].lower()
    assert result["answer_strategy"] == "identity_direct"
    assert result["answer_confidence"] == "high"
    assert result["sources"] == []
    assert "raiffeisenbank" in answer_lower
    assert "ai asistent" in answer_lower
    assert "uniqa" not in answer_lower
    assert "pojišťovna" not in answer_lower
    debug = result["retrieval_debug"][0]
    assert debug["retrieval_route"] == "identity"
    assert debug["retrieval_skipped"] is True
    assert debug["system_identity_route"] is True


def test_identity_route_synonyms():
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = FailingLLM()
    chain._retriever = FailingRetriever()

    for query in ["co umíte", "jsi RB?", "kdo je Raiffeisenbank", "s čím pomůžete"]:
        result = chain.ask(query)
        assert result["answer_strategy"] == "identity_direct"
        assert result["sources"] == []
        assert "Raiffeisenbank" in result["answer"]


def test_ekonto_pending_clarification_resolves_followup_without_losing_context():
    docs = [_pricing_row_doc()]
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.pending_clarification = None
    chain.clarification_context = None
    chain.resolved_product = None
    chain.resolved_intent = None
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever(docs)

    first = chain.ask("Kolik stojí eKonto?")
    assert first["answer_strategy"] == "clarification_direct"
    assert first["clarification_required"] is True
    assert chain.pending_clarification == "ekonto_pricing"

    second = chain.ask("osobní")
    assert second["answer_strategy"] == "pricing_row_direct"
    assert second["rewritten_query"] == "Kolik stojí vedení osobního eKonta?"
    assert chain.resolved_product == "osobní eKonto"
    assert chain.pending_clarification is None


def test_guided_card_blocking_flow_skips_retrieval():
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.clarification_context = None
    chain._llm = FailingLLM()
    chain._retriever = FailingRetriever()

    result = chain.ask("Ztratil jsem kartu")
    assert result["answer_strategy"] == "guided_flow_direct"
    assert result["sources"] == []
    assert "zablokujte" in result["answer"].lower()
    assert result["retrieval_debug"][0]["guided_flow"] == "card_blocking"
    assert result["confidence_bucket"] == "medium"


def test_card_overview_supported_answer_not_unsupported_or_clarification():
    doc = Document(
        page_content="Platební karty Raiffeisenbank Debetní karty Kreditní karty Mastercard Visa virtuální karta",
        metadata={
            "chunk_type": "section_text",
            "category": "cards",
            "source_url": "https://www.rb.cz/osobni/karty",
            "title": "Platební karty Raiffeisenbank",
            "overview_route_used": True,
            "supported_domain_detected": True,
            "unsupported_guard_bypassed": True,
            "fallback_card_retrieval_used": False,
        },
    )
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.clarification_context = None
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever([doc])

    result = chain.ask("Jaké typy platebních karet nabízíte?")

    assert result["answer_strategy"] == "card_overview_direct"
    assert result["unsupported_reason"] is None
    assert result["clarification_required"] is False
    assert result["confidence_bucket"] != "low"
    assert result["sources"]
    answer = result["answer"].lower()
    assert "debetní" in answer
    assert "kreditní" in answer
    assert "nepodařilo se najít" not in answer
    assert result["retrieval_debug"][0]["overview_route_used"] is True
    assert result["retrieval_debug"][0]["supported_domain_detected"] is True
    assert result["retrieval_debug"][0]["unsupported_guard_bypassed"] is True


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

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


def test_conditional_pricing_response_explains_active_and_inactive_fee():
    doc = Document(
        page_content="Produkt: eKonto SMART\nVedení účtu: podmíněně zdarma / jinak 99 Kč",
        metadata={
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "product_name": "eKonto SMART",
            "fee_type": "Vedení účtu",
            "fee_value": "podmíněně zdarma / jinak 99 Kč",
            "period": "měsíčně",
            "structured_pricing": True,
            "confidence": 0.95,
            "chunk_quality": "ok",
            "source_url": "https://www.rb.cz",
            "source_file": "cenik.pdf",
            "page": 2,
            "rerank_score": 1.0,
            "conditional_pricing_detected": True,
            "base_price": 99,
            "conditional_price": 0,
            "condition_type": "active_usage",
            "condition_text": "při aktivním využívání účtu",
            "pricing_logic": "conditional_price_applies_when_active_usage_else_base_price",
        },
    )
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever([doc])

    result = chain.ask("Kolik stojí vedení eKonto SMART?")

    assert result["answer_strategy"] == "pricing_row_direct"
    assert "eKonto SMART je zdarma při aktivním využívání účtu" in result["answer"]
    assert "Pokud podmínka splněna není, poplatek činí 99 Kč měsíčně" in result["answer"]
    assert "eKonto SMART je zdarma\n" not in result["answer"]


def test_tiered_pricing_response_lists_tiers():
    doc = Document(
        page_content="Produkt: Prémiový účet\nTarify: tiered",
        metadata={
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "product_name": "Prémiový účet",
            "fee_type": "Vedení účtu",
            "fee_value": "dle tarifu",
            "period": "měsíčně",
            "structured_pricing": True,
            "confidence": 0.95,
            "chunk_quality": "ok",
            "source_url": "https://www.rb.cz",
            "source_file": "cenik.pdf",
            "page": 2,
            "rerank_score": 1.0,
            "tiers": [
                {"label": "při splnění prémiových podmínek", "price": 0, "currency": "CZK", "period": "měsíčně"},
                {"label": "bez splnění podmínek", "price": 199, "currency": "CZK", "period": "měsíčně"},
            ],
        },
    )
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever([doc])

    result = chain.ask("Kolik stojí prémiový účet?")

    assert "* při splnění prémiových podmínek: 0 Kč měsíčně" in result["answer"]
    assert "* bez splnění podmínek: 199 Kč měsíčně" in result["answer"]


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


def test_clarification_followup_smart_maps_correctly():
    """Follow-up 'smart' after eKonto ambiguity must resolve to eKonto SMART."""
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.pending_clarification = None
    chain.clarification_context = None
    chain.resolved_product = None
    chain.resolved_intent = None
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever([_pricing_row_doc()])

    first = chain.ask("Kolik stojí eKonto?")
    assert first["answer_strategy"] == "clarification_direct"
    assert chain.pending_clarification == "ekonto_pricing"
    assert chain.clarification_candidates is not None

    second = chain.ask("smart")
    assert second["answer_strategy"] == "pricing_row_direct"
    assert chain.resolved_product == "eKonto SMART"
    assert chain.pending_clarification is None
    assert chain.last_canonical_product == "eKonto SMART"


def test_clarification_followup_podnikatelske_maps_correctly():
    """Follow-up 'podnikatelské' after eKonto ambiguity must resolve to business eKonto."""
    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.pending_clarification = None
    chain.clarification_context = None
    chain.resolved_product = None
    chain.resolved_intent = None
    chain._llm = FailingLLM()
    chain._retriever = FakeRetriever([_pricing_row_doc()])

    first = chain.ask("Kolik stojí eKonto?")
    assert first["answer_strategy"] == "clarification_direct"

    second = chain.ask("podnikatelské")
    assert chain.resolved_product == "podnikatelské eKonto"


def test_clarification_entity_memory_preserved(tmp_path):
    """Session entity memory must persist across the clarification flow."""
    from src.generation.chain import BankingRAGChain, _resolve_pending_clarification

    chain = BankingRAGChain.__new__(BankingRAGChain)
    chain.conversational = False
    chain.chat_history = []
    chain.pending_clarification = "ekonto_pricing"
    chain.clarification_context = {"type": "ekonto_pricing", "original_query": "Kolik stojí eKonto?"}
    chain.unresolved_product = "ekonto"
    chain.unresolved_product_type = "pricing"
    chain.clarification_candidates = ["osobní", "podnikatelské"]

    resolved = _resolve_pending_clarification("osobní", chain.clarification_context)
    assert resolved is not None
    rewritten, product, intent = resolved
    assert "osobního eKonta" in rewritten
    assert product == "osobní eKonto"
    assert intent == "pricing"


def test_generic_bezny_ucet_not_basic_payment():
    """Generic 'běžný účet' must NOT map to basic payment account."""
    from src.retrieval.pricing_resolver import resolve_pricing_query

    docs = resolve_pricing_query("Jaký je poplatek za vedení běžného účtu?", top_k=3)
    assert docs
    top = docs[0].metadata
    # Must resolve to mainstream eKonto SMART, not basic payment account
    assert top.get("product_name") == "eKonto SMART"
    assert top.get("mainstream_product") is True or top.get("mainstream_boost_applied") is True
    assert top.get("pricing_row_exact_match") is True

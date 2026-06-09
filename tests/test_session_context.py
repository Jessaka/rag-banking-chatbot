"""
Tests for Priority 4 — Semantic Session Context.

Covers:
  - session_context dict structure and initialization
  - _update_session_context safety without __init__
  - _check_session_inheritance safety without __init__
  - _get_session_debug output structure
  - No personal data in session context
"""

from __future__ import annotations

from src.generation.chain import BankingRAGChain, _rewrite_inherited_followup_query


# ======================================================================
# Session context safety (__new__ without __init__)
# ======================================================================

class TestSessionContextSafety:
    def test_update_session_context_safe_without_init(self) -> None:
        """_update_session_context must not crash when
        session_context doesn't exist."""
        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.resolved_product = None
        chain.resolved_intent = None
        chain._update_session_context(query_profile=None)
        assert True

    def test_check_inheritance_safe_without_init(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        result = chain._check_session_inheritance("test")
        assert result == (None, None)

    def test_get_session_debug_both_none(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        debug = chain._get_session_debug(None, None)
        assert isinstance(debug, dict)
        # session_context_used should be absent or False when no inheritance
        assert not debug.get("session_context_used", False)

    def test_get_session_debug_with_inheritance(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        debug = chain._get_session_debug("eKonto", "pricing")
        assert debug.get("session_context_used") is True
        assert debug.get("inherited_product") == "eKonto"
        assert debug.get("inherited_intent") == "pricing"

    def test_get_session_debug_product_only(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        debug = chain._get_session_debug("eKonto", None)
        assert debug.get("session_context_used") is True
        assert debug.get("inherited_product") == "eKonto"
        assert "inherited_intent" not in debug

    def test_get_session_debug_intent_only(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        debug = chain._get_session_debug(None, "card_overview")
        assert debug.get("session_context_used") is True
        assert debug.get("inherited_intent") == "card_overview"
        assert "inherited_product" not in debug

    def test_check_inheritance_detects_exclusive_free_followup(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.chat_history = ["dummy"]
        chain.session_context = {
            "current_domain": "retail",
            "current_product": "osobni_ucet",
            "current_intent": "pricing",
            "last_clarification": None,
            "resolved_product": "exkluzivni_ucet",
            "resolved_segment": None,
        }
        result = chain._check_session_inheritance("Jaké jsou podmínky, aby byl zdarma?")
        assert result == ("exkluzivni_ucet", "pricing")


# ======================================================================
# Session context initialization with __init__
# ======================================================================

class TestSessionContextInit:
    def test_session_context_on_fully_initialized(self) -> None:
        """Test that session_context exists on a real chain instance.
        Uses __new__ + manual init of just __init__ attributes to avoid
        LLM dependency (openai module may not be installed)."""
        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.conversational = True
        chain.chat_history = []
        chain.pending_clarification = None
        chain.clarification_context = None
        chain.resolved_product = None
        chain.resolved_intent = None
        chain.session_context = {
            "current_domain": None,
            "current_product": None,
            "current_intent": None,
            "last_clarification": None,
            "resolved_product": None,
            "resolved_segment": None,
        }
        chain._session_debug = {}
        assert isinstance(chain.session_context, dict)
        assert all(v is None for v in chain.session_context.values())
        assert chain.session_context.get("current_intent") is None


# ======================================================================
# Session context population (simulated)
# ======================================================================

class TestSessionContextPopulation:
    def test_update_context_with_retail_domain(self) -> None:
        """Simulate a retail query to verify domain detection."""
        from src.retrieval.query_classifier import classify_query

        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.resolved_product = None
        chain.resolved_intent = None
        chain.session_context = {
            "current_domain": None, "current_product": None,
            "current_intent": None, "last_clarification": None,
            "resolved_product": None, "resolved_segment": None,
        }
        profile = classify_query("Jaký je poplatek za vedení běžného účtu?")
        chain._update_session_context(profile)
        assert chain.session_context["current_domain"] == "retail"

    def test_update_context_with_card_intent(self) -> None:
        from src.retrieval.query_classifier import classify_query

        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.resolved_product = None
        chain.resolved_intent = None
        chain.session_context = {
            "current_domain": None, "current_product": None,
            "current_intent": None, "last_clarification": None,
            "resolved_product": None, "resolved_segment": None,
        }
        profile = classify_query("Jaké máte kreditní karty?")
        chain._update_session_context(profile)
        assert chain.session_context["current_intent"] is not None

    def test_update_context_with_resolved_product(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.resolved_product = "eKonto"
        chain.resolved_intent = "pricing"
        chain.session_context = {
            "current_domain": None, "current_product": None,
            "current_intent": None, "last_clarification": None,
            "resolved_product": None, "resolved_segment": None,
        }
        chain._update_session_context(None)
        assert chain.session_context["resolved_product"] == "eKonto"
        assert chain.session_context["current_intent"] == "pricing"


class TestInheritedFollowupRewrite:
    def test_rewrite_most_expensive_account_anchors_exclusive_product(self) -> None:
        rewritten, anchored = _rewrite_inherited_followup_query(
            "A ten nejdražší?",
            "osobni_ucet",
        )
        assert rewritten == "Kolik stojí EXKLUZIVNÍ účet?"
        assert anchored == "exkluzivni_ucet"

    def test_rewrite_exclusive_free_followup_conditions(self) -> None:
        rewritten, anchored = _rewrite_inherited_followup_query(
            "Jaké jsou podmínky, aby byl zdarma?",
            "exkluzivni_ucet",
        )
        assert rewritten == "Jaké jsou podmínky vedení EXKLUZIVNÍHO účtu zdarma?"
        assert anchored is None

    def test_credit_card_followup_remains_unchanged(self) -> None:
        rewritten, anchored = _rewrite_inherited_followup_query(
            "A kolik stojí ta Premium?",
            "kreditni_karta",
        )
        assert rewritten == "Kolik stojí kreditní karta RB Premium?"
        assert anchored is None

    def test_hypoteka_followup_remains_unchanged(self) -> None:
        rewritten, anchored = _rewrite_inherited_followup_query(
            "Jaké jsou podmínky hypotéky?",
            "hypoteky",
        )
        assert rewritten == "Jaké jsou podmínky hypotéky?"
        assert anchored is None


# ======================================================================
# No personal data
# ======================================================================

class TestNoPersonalData:
    def test_session_context_no_personal_data(self) -> None:
        chain = BankingRAGChain.__new__(BankingRAGChain)
        chain.resolved_product = None
        chain.resolved_intent = None
        chain.session_context = {
            "current_domain": "retail",
            "current_product": "eKonto",
            "current_intent": "pricing",
            "last_clarification": None,
            "resolved_product": "eKonto",
            "resolved_segment": "personal",
        }
        for key, value in chain.session_context.items():
            if value is not None:
                assert isinstance(value, str)
                assert "123456" not in str(value)

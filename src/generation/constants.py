"""Central constants and typed enums for the RB banking RAG chatbot.

Consolidates all route strategies, confidence buckets, source authority tiers,
freshness buckets, and capability flags into a single source of truth.

Usage:
    from src.generation.constants import RouteStrategy, ConfidenceBucket

    strategy = RouteStrategy.PRICING_ROW_DIRECT
    if strategy == RouteStrategy.PRICING_ROW_DIRECT:
        ...
"""

from __future__ import annotations

from enum import Enum


class RouteStrategy(str, Enum):
    """All possible answer strategies — single source of truth.

    Each value is the exact string used in chain.py return dicts and
    confidence_semantics.py mappings. Using enum members instead of
    hardcoded strings prevents typos and enables IDE autocompletion.
    """

    # Identity
    IDENTITY_DIRECT = "identity_direct"

    # Guided / procedural
    GUIDED_FLOW_DIRECT = "guided_flow_direct"
    PROCEDURAL_FLOW_DIRECT = "procedural_flow_direct"

    # Unsupported / clarification
    UNSUPPORTED_DIRECT = "unsupported_direct"
    FALLBACK_NO_ANSWER = "fallback_no_answer"
    CLARIFICATION_DIRECT = "clarification_direct"

    # Overview routes
    CARD_OVERVIEW_DIRECT = "card_overview_direct"
    ACCOUNT_OVERVIEW_DIRECT = "account_overview_direct"
    MORTGAGE_OVERVIEW_DIRECT = "mortgage_overview_direct"
    INVESTMENT_OVERVIEW_DIRECT = "investment_overview_direct"
    RB_KEY_OVERVIEW_DIRECT = "rb_key_overview_direct"
    PAYMENT_OVERVIEW_DIRECT = "payment_overview_direct"
    SEPA_SWIFT_OVERVIEW_DIRECT = "sepa_swift_overview_direct"
    PRODUCT_OVERVIEW_DIRECT = "product_overview_direct"
    CREDIT_CARD_CATALOG_DIRECT = "credit_card_catalog_direct"
    CARD_BRAND_OVERVIEW = "card_brand_overview"

    # Soft guidance
    SOFT_GUIDANCE_DIRECT = "soft_guidance_direct"

    # Pricing
    PRICING_ROW_DIRECT = "pricing_row_direct"
    PRICING_TABLE_LLM = "pricing_table_llm"
    PRICING_SECTION_LLM = "pricing_section_llm"

    # LLM fallback
    GENERIC_LLM = "generic_llm"

    # Degradation
    OVERVIEW_FALLBACK = "overview_fallback"

    # Comparison
    COMPARISON_DIRECT = "comparison_direct"

    @classmethod
    def overview_routes(cls) -> set[str]:
        """Return all overview-direct strategy values."""
        return {
            cls.CARD_OVERVIEW_DIRECT,
            cls.ACCOUNT_OVERVIEW_DIRECT,
            cls.MORTGAGE_OVERVIEW_DIRECT,
            cls.INVESTMENT_OVERVIEW_DIRECT,
            cls.RB_KEY_OVERVIEW_DIRECT,
            cls.PAYMENT_OVERVIEW_DIRECT,
            cls.SEPA_SWIFT_OVERVIEW_DIRECT,
            cls.PRODUCT_OVERVIEW_DIRECT,
            cls.CREDIT_CARD_CATALOG_DIRECT,
        }

    @classmethod
    def deterministic_routes(cls) -> set[str]:
        """Routes that never invoke the LLM."""
        overview = cls.overview_routes()
        return overview | {
            cls.IDENTITY_DIRECT,
            cls.GUIDED_FLOW_DIRECT,
            cls.PROCEDURAL_FLOW_DIRECT,
            cls.UNSUPPORTED_DIRECT,
            cls.CLARIFICATION_DIRECT,
            cls.SOFT_GUIDANCE_DIRECT,
            cls.FALLBACK_NO_ANSWER,
            cls.CREDIT_CARD_CATALOG_DIRECT,
            cls.COMPARISON_DIRECT,
        }

    @classmethod
    def degraded_routes(cls) -> set[str]:
        """Routes that indicate a fallback from the primary strategy."""
        return {
            cls.OVERVIEW_FALLBACK,
            cls.UNSUPPORTED_DIRECT,
            cls.FALLBACK_NO_ANSWER,
            cls.SOFT_GUIDANCE_DIRECT,
        }


class ConfidenceBucket(str, Enum):
    """Confidence levels for answers."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceFreshnessBucket(str, Enum):
    """Freshness classification for source documents."""
    CURRENT = "current"
    RECENT = "recent"
    STALE = "stale"
    ARCHIVED = "archived"


class AuthorityTier(str, Enum):
    """Document authority tiers."""
    PRODUCT_PAGE = "product_page"
    FAQ_SUPPORT_PAGE = "faq_support_page"
    CURRENT_PRICING = "current_pricing"
    CURRENT_PDF = "current_pdf"
    GENERIC_PAGE = "generic_page"
    HISTORICAL_PDF = "historical_pdf"
    MIGRATION_NOTICE = "migration_notice"
    ARCHIVED_LEGAL = "archived_legal"
    UNKNOWN = "unknown"

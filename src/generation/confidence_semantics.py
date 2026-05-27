"""Confidence semantics — maps confidence buckets to human-readable labels,
origin tracking, and degradation status.

Provides:
- Semantic confidence labels for frontend display
- Confidence origin tracking (pricing_row, procedural, identity, etc.)
- Degradation detection for fallback answers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConfidenceBucket = Literal["high", "medium", "low"]
ConfidenceOrigin = Literal[
    "pricing_row",          # Exact deterministic pricing row match
    "procedural",           # Deterministic procedural flow
    "identity",             # Identity verification (deterministic)
    "overview_direct",      # Deterministic overview (card_overview_direct, etc.)
    "overview_fallback",    # Graceful degradation: product overview without pricing
    "clarification",        # Clarification required
    "llm_generated",        # Free-form LLM answer with source backing
    "soft_guidance",        # Soft guidance / FAQ with weak retrieval
    "unsupported",          # No reliable answer found
]


# ---------------------------------------------------------------------------
# Semantic label mapping
# ---------------------------------------------------------------------------

CONFIDENCE_SEMANTIC_LABELS: dict[ConfidenceBucket, str] = {
    "high": "Ověřeno ve zdrojích RB",
    "medium": "Doporučená odpověď",
    "low": "Vyžaduje ověření",
}

CONFIDENCE_ORIGIN_LABELS: dict[ConfidenceOrigin, str] = {
    "pricing_row": "Přesná ceníková položka",
    "procedural": "Určeno interním postupem",
    "identity": "Prověřeno identitou",
    "overview_direct": "Sestaveno z produktových informací",
    "overview_fallback": "Sestaveno z popisu produktu",
    "clarification": "Vyžaduje upřesnění",
    "llm_generated": "Generováno na základě zdrojů",
    "soft_guidance": "Obecné doporučení na základě FAQ",
    "unsupported": "Nelze spolehlivě odpovědět",
}


# ---------------------------------------------------------------------------
# Origin → bucket mapping for deterministic assignment
# ---------------------------------------------------------------------------

ORIGIN_BUCKET_MAP: dict[ConfidenceOrigin, ConfidenceBucket] = {
    "pricing_row": "high",
    "procedural": "high",
    "identity": "high",
    "overview_direct": "medium",
    "overview_fallback": "medium",
    "clarification": "medium",
    "llm_generated": "medium",
    "soft_guidance": "medium",
    "unsupported": "low",
}


# ---------------------------------------------------------------------------
# Strategy → origin mapping
# ---------------------------------------------------------------------------

STRATEGY_ORIGIN_MAP: dict[str, ConfidenceOrigin] = {
    "identity_direct": "identity",
    "guided_flow_direct": "procedural",
    "procedural_flow_direct": "procedural",
    "pricing_row_direct": "pricing_row",
    "pricing_table_llm": "llm_generated",
    "pricing_section_llm": "llm_generated",
    "generic_llm": "llm_generated",
    "card_overview_direct": "overview_direct",
    "account_overview_direct": "overview_direct",
    "mortgage_overview_direct": "overview_direct",
    "investment_overview_direct": "overview_direct",
    "rb_key_overview_direct": "overview_direct",
    "payment_overview_direct": "overview_direct",
    "sepa_swift_overview_direct": "overview_direct",
    "product_overview_direct": "overview_direct",
    "credit_card_catalog_direct": "overview_direct",
    "soft_guidance_direct": "soft_guidance",
    "clarification_direct": "clarification",
    "unsupported_direct": "unsupported",
    "fallback_no_answer": "unsupported",
    "overview_fallback": "overview_fallback",
    "comparison_direct": "overview_direct",
}

# Strategies that count as "degraded" (fallback from primary route)
DEGRADED_STRATEGIES: frozenset = frozenset({
    "overview_fallback",
    "unsupported_direct",
    "fallback_no_answer",
    "soft_guidance_direct",
})


@dataclass
class ConfidenceSemantics:
    """Enriched confidence metadata for a single response."""
    bucket: ConfidenceBucket
    semantic_label: str
    origin: ConfidenceOrigin
    origin_label: str
    degraded: bool = False
    reason: str = ""


def resolve_confidence_semantics(
    strategy: str,
    bucket: ConfidenceBucket | None = None,
    reason: str = "",
    *,
    force_degraded: bool = False,
) -> ConfidenceSemantics:
    """Resolve full confidence semantics from an answer strategy.

    Args:
        strategy: The answer_strategy value.
        bucket: Override bucket (if already computed). If None, derived from origin.
        reason: Human-readable confidence reason.
        force_degraded: Override degraded flag.

    Returns:
        ConfidenceSemantics with all enrichment fields.
    """
    origin = STRATEGY_ORIGIN_MAP.get(strategy, "llm_generated")
    if bucket is None:
        bucket = ORIGIN_BUCKET_MAP.get(origin, "medium")

    degraded = force_degraded or strategy in DEGRADED_STRATEGIES
    semantic_label = CONFIDENCE_SEMANTIC_LABELS.get(bucket, "Vyžaduje ověření")
    origin_label = CONFIDENCE_ORIGIN_LABELS.get(origin, "Generováno na základě zdrojů")

    return ConfidenceSemantics(
        bucket=bucket,
        semantic_label=semantic_label,
        origin=origin,
        origin_label=origin_label,
        degraded=degraded,
        reason=reason or origin_label,
    )


def bucket_for_origin(origin: ConfidenceOrigin) -> ConfidenceBucket:
    """Return the default bucket for a confidence origin."""
    return ORIGIN_BUCKET_MAP.get(origin, "medium")

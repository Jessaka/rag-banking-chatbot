"""Deterministic comparison engine for RB banking products.

Provides structured, hallucination-free product comparisons by matching
entities from the product registry and formatting them into a safe
comparison table.

No LLM involved — all output is sourced from PRODUCT_REGISTRY metadata
with safe fallbacks when data is insufficient.
"""

from __future__ import annotations

import re
from typing import Any

from src.generation.product_intelligence import (
    PRODUCT_REGISTRY,
    ProductInfo,
    find_product_by_canonical_label,
    get_product,
)

# ---------------------------------------------------------------------------
# Comparison pairs — known meaningful comparisons between RB products
# ---------------------------------------------------------------------------

COMPARISON_PAIRS: dict[frozenset[str], dict[str, Any]] = {
    frozenset({"ekonto_osobni", "aktivni_ucet"}): {
        "label_cs": "Osobní eKonto vs Aktivní účet",
        "dimensions": ("typ_uctu", "poplatek", "vyhody", "urceni"),
    },
    frozenset({"debetni_karta", "kreditni_karta"}): {
        "label_cs": "Debetní vs Kreditní karta",
        "dimensions": ("typ_karty", "poplatek", "limit", "pouziti", "urok"),
    },
    frozenset({"kreditni_karta", "debetni_karta"}): {
        "label_cs": "Debetní vs Kreditní karta",
        "dimensions": ("typ_karty", "poplatek", "limit", "pouziti", "urok"),
    },
}

# ---------------------------------------------------------------------------
# Comparison keywords for intent detection
# ---------------------------------------------------------------------------

COMPARISON_KEYWORDS = (
    "rozdíl", "rozdil", "vs", "versus", "nebo", "porovnání", "porovnani",
    "jaký je rozdíl", "jaky je rozdil", "čím se liší", "cim se lisi",
    "co je lepší", "co je lepsi", "který", "ktery",
)

# Known product name aliases (from query text → product_id)
PRODUCT_ALIASES: dict[str, str] = {
    "osobní eKonto": "ekonto_osobni",
    "osobni ekonto": "ekonto_osobni",
    "ekonto osobní": "ekonto_osobni",
    "ekonto": "ekonto_osobni",
    "aktivní účet": "aktivni_ucet",
    "aktivní ucet": "aktivni_ucet",
    "aktivni účet": "aktivni_ucet",
    "aktivni ucet": "aktivni_ucet",
    "debetní karta": "debetni_karta",
    "debetní kartou": "debetni_karta",
    "debetni karta": "debetni_karta",
    "kreditní karta": "kreditni_karta",
    "kreditní kartou": "kreditni_karta",
    "kreditni karta": "kreditni_karta",
    "kreditka": "kreditni_karta",
    "debetka": "debetni_karta",
    "visa": "debetni_karta",
    "mastercard": "debetni_karta",
    "hypotéka 3": "hypoteky",
    "hypotéka 5": "hypoteky",
    "hypoteka 3": "hypoteky",
    "hypoteka 5": "hypoteky",
    "fixace 3": "hypoteky",
    "fixace 5": "hypoteky",
    "fixace na 3": "hypoteky",
    "fixace na 5": "hypoteky",
}


def detect_comparison_entities(question: str) -> list[str] | None:
    """Detect product entities being compared in a query.

    Args:
        question: The user's question.

    Returns:
        A list of product_ids being compared, or None if no comparison detected.
    """
    q = question.lower().strip()

    # Must contain comparison signal
    has_signal = any(kw in q for kw in COMPARISON_KEYWORDS)
    if not has_signal:
        return None

    # Extract known product aliases from the question
    found_ids: list[str] = []
    for alias, pid in sorted(PRODUCT_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in q and pid not in found_ids:
            found_ids.append(pid)

    # Need at least 2 products to compare
    if len(found_ids) >= 2:
        return found_ids[:2]  # Max 2 entities

    # Single product found — could be comparison with implicit entity
    # e.g. "Co je lepší, eKonto?" → might need clarification
    if len(found_ids) == 1:
        # Check if query mentions specific comparison domain
        domain_map = {
            "karta": "cards",
            "účet": "osobni_ucty",
            "ucet": "osobni_ucty",
            "hypotéka": "hypoteky",
            "hypoteka": "hypoteky",
        }
        for term, _domain in domain_map.items():
            if term in q:
                found_ids.append(found_ids[0])  # Compare same category
                return found_ids

    return None  # Not enough entities


def format_comparison_answer(entities: list[str]) -> str | None:
    """Format a deterministic comparison answer for the given product entities.

    Args:
        entities: List of product_ids (exactly 2).

    Returns:
        A formatted comparison string, or None if data is insufficient.
    """
    if len(entities) != 2:
        return None

    pid_a, pid_b = entities
    prod_a = get_product(pid_a) or find_product_by_canonical_label(pid_a)
    prod_b = get_product(pid_b) or find_product_by_canonical_label(pid_b)

    if not prod_a or not prod_b:
        return None

    # Check if this is a known comparison pair
    pair_key = frozenset({pid_a, pid_b})
    pair_config = COMPARISON_PAIRS.get(pair_key)

    # Build comparison table
    lines: list[str] = []
    lines.append(f"**Srovnání: {prod_a.display_name} vs {prod_b.display_name}**")
    lines.append("")

    # Description row
    lines.append(f"- **{prod_a.display_name}**: {prod_a.short_description}")
    lines.append(f"- **{prod_b.display_name}**: {prod_b.short_description}")
    lines.append("")

    if pair_config:
        lines.append("| Aspekt | {} | {} |".format(prod_a.display_name, prod_b.display_name))
        lines.append("|---|---|---|")

        # Dimension-based comparison
        for dim in pair_config.get("dimensions", ()):
            row_a = _describe_dimension(prod_a, dim)
            row_b = _describe_dimension(prod_b, dim)
            dim_label = _dimension_label(dim)
            if row_a and row_b:
                lines.append(f"| **{dim_label}** | {row_a} | {row_b} |")

        lines.append("")

    # Capabilities
    caps_a = ", ".join(_capability_label(c) for c in prod_a.capabilities)
    caps_b = ", ".join(_capability_label(c) for c in prod_b.capabilities)
    lines.append(f"**{prod_a.display_name}** nabízí: {caps_a}")
    lines.append(f"**{prod_b.display_name}** nabízí: {caps_b}")
    lines.append("")

    # Pricing notes if available
    if prod_a.pricing_note or prod_b.pricing_note:
        lines.append("**Cena a poplatky:**")
        if prod_a.pricing_note:
            lines.append(f"- {prod_a.display_name}: {prod_a.pricing_note}")
        if prod_b.pricing_note:
            lines.append(f"- {prod_b.display_name}: {prod_b.pricing_note}")
        lines.append("")

    # CTA if available
    ctas = []
    if prod_a.cta_text:
        ctas.append(prod_a.cta_text)
    if prod_b.cta_text:
        ctas.append(prod_b.cta_text)
    if ctas:
        lines.append(" | ".join(ctas))

    if len(lines) <= 2:
        return None  # Nothing meaningful to show

    return "\n".join(lines)


def _describe_dimension(product: ProductInfo, dimension: str) -> str | None:
    """Describe a product along a specific comparison dimension."""
    dim_descriptions = {
        "typ_uctu": {
            "ekonto_osobni": "Osobní běžný účet s tarifními variantami",
            "aktivni_ucet": "Běžný účet s odměnou za aktivní používání",
        },
        "typ_karty": {
            "debetni_karta": "Debetní — platíte svými penězi",
            "kreditni_karta": "Kreditní — platíte na úvěr s bezúročným obdobím",
        },
        "poplatek": {
            "ekonto_osobni": "Měsíční poplatek dle tarifu (0–199 Kč)",
            "aktivni_ucet": "Měsíční poplatek 0 Kč při aktivitě, jinak 149 Kč",
            "debetni_karta": "Obvykle zdarma k účtu",
            "kreditni_karta": "Dle typu karty (často 0–99 Kč/měsíc)",
        },
        "vyhody": {
            "ekonto_osobni": "Výběr ze 3 tarifů, cestovní pojištění",
            "aktivni_ucet": "Odměna za aktivitu, cashback",
        },
        "urceni": {
            "ekonto_osobni": "Klienti, kteří chtějí standardní bankovnictví",
            "aktivni_ucet": "Klienti, kteří bankují aktivně a chtějí odměny",
        },
        "limit": {
            "debetni_karta": "Limit = disponibilní zůstatek na účtu",
            "kreditni_karta": "Schválený úvěrový limit (např. 5 000–150 000 Kč)",
        },
        "pouziti": {
            "debetni_karta": "Platby a výběry z vlastních peněz",
            "kreditni_karta": "Platby a výběry na úvěr, nákupy online",
        },
        "urok": {
            "debetni_karta": "Bez úroku (platíte z vlastního zůstatku)",
            "kreditni_karta": "Úrok při nedodržení bezúročného období",
        },
    }
    dim_map = dim_descriptions.get(dimension, {})
    return dim_map.get(product.product_id)


def _dimension_label(dimension: str) -> str:
    """Human-readable label for a comparison dimension."""
    labels = {
        "typ_uctu": "Typ účtu",
        "typ_karty": "Typ karty",
        "poplatek": "Poplatek",
        "vyhody": "Výhody",
        "urceni": "Určení",
        "limit": "Limit",
        "pouziti": "Použití",
        "urok": "Úrok",
        "karta": "Karta",
    }
    return labels.get(dimension, dimension.replace("_", " ").title())


def _capability_label(cap: str) -> str:
    """Human-readable label for a capability flag."""
    labels = {
        "vedeni": "vedení účtu",
        "platebni_styk": "platební styk",
        "internetove_bankovnictvi": "internetové bankovnictví",
        "karta": "platební karta",
        "kreditni_karta": "kreditní karta",
        "debetni_karta": "debetní karta",
        "hypoteka": "hypotéka",
        "investice": "investice",
        "sporeni": "spoření",
        "pujcka": "půjčka",
        "sepa_swift": "SEPA/SWIFT platby",
        "apple_google_pay": "Apple Pay / Google Pay",
        "bezpecnost": "bezpečnost",
        "rb_klic": "RB Klíč",
    }
    return labels.get(cap, cap.replace("_", " "))

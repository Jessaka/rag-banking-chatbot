"""Canonical Pricing Resolver for deterministic banking pricing truth.

This module is orchestration-only: it does not crawl, ingest, reindex, mutate
Qdrant, change embeddings, or change any schema.  It resolves pricing from the
existing structured pricing JSONL rows and returns LangChain ``Document``
objects compatible with the current generation chain.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

# Rychlý pre-filter před drahou canonical_product_for_row() regex analýzou.
# Klíčová slova se kontrolují na product_name.lower() — O(1) substring check.
# Musí být permisivní (false positive ok, false negative ne).
# Termy jsou bez diakritiky (po _norm()) aby matchovaly i "Základní" → "zakladni"
_CANONICAL_QUICK_TERMS: dict[str, tuple[str, ...]] = {
    "ekonto_osobni":         ("ekonto", "e konto", "e-konto", "chytry ucet", "aktivni ucet", "exkluzivni"),
    "ekonto_podnikatelske":  ("ekonto", "podnikatel", "business", "osvc"),
    "osobni_ucet":           ("osobni", "bezny", "ekonto", "studentsk", "detsk"),
    "podnikatelsky_ucet":    ("podnikatel", "business", "osvc", "ekonto"),
    "firemni_ucet":          ("firemni", "firma", "firmy", "corporate"),
    "kreditni_karta":        ("kredit", "credit"),
    "rb_premium_karta":      ("kredit", "credit", "premium", "rb premium"),
    "easy_karta":            ("kredit", "credit"),
    "style_karta":           ("kredit", "credit"),
    "visa_gold_karta":       ("kredit", "credit", "visa"),
    "o2_rb_karta":           ("kredit", "credit", "o2"),
    "debetni_karta":         ("debet", "debit"),
    "hypoteky":              ("hypot",),
    "pujcky":                ("pujck", "uver", "spotreb"),
    "sporeni":               ("sporic", "sporeni", "terminovan", "vklad"),
    "investice":             ("investic", "fond", "dluhopis"),
    "basic_payment_account": ("zakladni platebni", "chraneny ucet", "social", "zakladni platebni ucet"),
}

from langchain_core.documents import Document

from src.ingestion.quality_filters import is_valid_pricing_row
from src.retrieval.pricing_retriever import (
    CANONICAL_PRODUCT_LABELS,
    PRODUCT_MATCH_CONFIDENCE_THRESHOLD,
    QueryProfile,
    _is_archive_query,
    _is_basic_payment_account_query,
    _is_basic_payment_account_row,
    _is_mainstream_row,
    _is_niche_product_row,
    _is_row_archived,
    _normalize_pricing_metadata,
    _norm,
    _product_group_match,
    _product_match_strength,
    _row_text,
    _score_row,
    canonical_product_for_row,
    classify_query,
    detect_query_product,
    is_primary_account_fee_query,
    is_primary_account_fee_row,
    load_pricing_rows,
    product_segment_for_row,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

SAFE_PRICING_FALLBACK_MESSAGE = (
    "Nepodařilo se jednoznačně určit aktuální poplatek pro tento produkt. "
    "Doporučuji otevřít aktuální ceník RB."
)

SOURCE_PRIORITY = {
    "current_pricing_pdf": 100,
    "official_pricing_table": 90,
    "structured_pricing_chunk": 80,
    "product_pricing_page": 70,
    "faq": 40,
    "generic_overview": 10,
}

FREE_PATTERNS = (
    r"\bzdarma\b",
    r"\b0\s*(?:kč|kc|czk)\b",
    r"\bbez\s+poplatku\b",
    r"\bměsíčně\s+zdarma\b",
    r"\bmesicne\s+zdarma\b",
    r"\bvedení\s+zdarma\b",
    r"\bvedeni\s+zdarma\b",
    r"\bfee\s+waived\b",
    r"\bfirst\s+year\s+free\b",
)


@dataclass(frozen=True)
class NormalizedPrice:
    normalized_price: float | int | None
    currency: str | None
    billing_period: str | None
    semantic_label: str
    raw_value: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_price": self.normalized_price,
            "currency": self.currency,
            "billing_period": self.billing_period,
            "semantic_label": self.semantic_label,
            "raw_value": self.raw_value,
        }


@dataclass(frozen=True)
class ConditionalPricing:
    base_price: float | int | None
    conditional_price: float | int | None
    currency: str | None
    billing_period: str | None
    condition_type: str | None
    condition_text: str | None
    pricing_logic: str
    tiers: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "conditional_pricing_detected": True,
            "base_price": self.base_price,
            "conditional_price": self.conditional_price,
            "currency": self.currency,
            "billing_period": self.billing_period,
            "condition_type": self.condition_type,
            "condition_text": self.condition_text,
            "pricing_logic": self.pricing_logic,
            "tiers": self.tiers,
        }


def normalize_price(value: str, *, period: str | None = None) -> dict[str, Any]:
    """Normalize Czech/English free and numeric pricing values."""
    raw = str(value or "").strip()
    norm = _norm(raw)
    period_norm = _norm(str(period or ""))
    if any(re.search(pattern, raw, flags=re.IGNORECASE) or re.search(pattern, norm, flags=re.IGNORECASE) for pattern in FREE_PATTERNS):
        return NormalizedPrice(0, "CZK", _billing_period(raw, period_norm), "free", raw).as_dict()

    amount_match = re.search(r"\d+(?:[\s.]\d{3})*(?:[,.]\d+)?", raw)
    amount: float | int | None = None
    if amount_match:
        amount_text = amount_match.group(0).replace(" ", "").replace(".", "").replace(",", ".")
        try:
            amount = float(amount_text)
            if amount.is_integer():
                amount = int(amount)
        except ValueError:
            amount = None
    currency = "CZK" if any(token in norm for token in ("kc", "czk", "kč")) or amount == 0 else None
    if "eur" in norm or "€" in raw:
        currency = "EUR"
    semantic = "amount" if amount is not None else "unknown"
    return NormalizedPrice(amount, currency, _billing_period(raw, period_norm), semantic, raw).as_dict()


def normalize_row_price(row: dict) -> dict[str, Any]:
    """Normalize a row price, including current rows that explicitly abolish a fee."""
    conditional = detect_conditional_pricing(row)
    if conditional:
        data = conditional.as_dict()
        return NormalizedPrice(None, data.get("currency"), data.get("billing_period"), "conditional", str(row.get("fee_value") or "")).as_dict()
    if _is_fee_abolished_row(row):
        return NormalizedPrice(0, "CZK", "monthly", "free", str(row.get("fee_value") or "")).as_dict()
    return normalize_price(str(row.get("fee_value") or row.get("amount") or ""), period=str(row.get("period") or ""))


def _price_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    normalized = normalize_price(str(value))
    amount = normalized.get("normalized_price")
    return amount if isinstance(amount, (int, float)) else None


def _condition_type(text: str) -> str | None:
    norm = _norm(text)
    if any(token in norm for token in ("aktivnim vyuziv", "aktivne vyuziv", "aktivni vyuziv", "aktivni pouziv")):
        return "active_usage"
    if any(token in norm for token in ("obrat", "obratu")):
        return "turnover"
    if any(token in norm for token in ("minimalni prijem", "prijem", "prichozich plateb", "prichozi platby")):
        return "minimum_income"
    if any(token in norm for token in ("premium", "premiovy", "premiove", "vyhody premium")):
        return "premium_tier"
    if any(token in norm for token in ("pri splneni podminek", "splneni podminek", "podmink")):
        return "condition_met"
    return None


def detect_conditional_pricing(row: dict) -> ConditionalPricing | None:
    """Detect conditional/tiered/activity-dependent pricing without flattening it."""
    if row.get("conditional_pricing_detected") is True or row.get("condition_type") or row.get("conditional_price") is not None:
        base_price = _price_number(row.get("base_price") if row.get("base_price") is not None else row.get("fee_value"))
        conditional_price = _price_number(row.get("conditional_price"))
        condition_text = str(row.get("condition_text") or row.get("conditions") or "").strip() or None
        condition_type = str(row.get("condition_type") or _condition_type(condition_text or "") or "condition_met")
        return ConditionalPricing(
            base_price=base_price,
            conditional_price=conditional_price,
            currency=str(row.get("currency") or "CZK"),
            billing_period=_billing_period(str(row.get("fee_value") or ""), _norm(str(row.get("period") or ""))),
            condition_type=condition_type,
            condition_text=condition_text,
            pricing_logic=str(row.get("pricing_logic") or "conditional_price_applies_when_condition_met_else_base_price"),
            tiers=list(row.get("tiers") or []),
        )

    text = " ".join(str(row.get(k) or "") for k in ("product_name", "fee_type", "fee_value", "period", "conditions", "title"))
    norm = _norm(text)
    conditional_signal = any(token in norm for token in (
        "zdarma pri aktivnim vyuzivani",
        "pri aktivnim vyuzivani",
        "pokud neni ucet aktivne vyuzivan",
        "pri splneni podminek",
        "pri obratu",
        "minimalnim prijmu",
        "minimalni prijem",
        "premium tier",
    ))
    if not conditional_signal:
        return None

    amounts = re.findall(r"\d+(?:[\s.]\d{3})*(?:[,.]\d+)?\s*(?:Kč|CZK|kc|kč)?", text, flags=re.IGNORECASE)
    parsed_amounts = [_price_number(amount) for amount in amounts]
    parsed_amounts = [amount for amount in parsed_amounts if amount is not None]
    conditional_price = 0 if "zdarma" in norm else (parsed_amounts[0] if parsed_amounts else None)
    base_candidates = [amount for amount in parsed_amounts if amount != conditional_price]
    base_price = base_candidates[-1] if base_candidates else _price_number(row.get("base_price"))
    condition_text = str(row.get("condition_text") or row.get("conditions") or "").strip() or None
    if not condition_text and "aktiv" in norm:
        condition_text = "při aktivním využívání účtu"
    ctype = _condition_type(text) or "condition_met"
    return ConditionalPricing(
        base_price=base_price,
        conditional_price=conditional_price,
        currency="CZK" if (base_price is not None or conditional_price is not None) else None,
        billing_period=_billing_period(text, _norm(str(row.get("period") or ""))),
        condition_type=ctype,
        condition_text=condition_text,
        pricing_logic="conditional_price_applies_when_condition_met_else_base_price",
        tiers=[],
    )


def pricing_source_type(row: dict) -> str:
    """Classify pricing source type for deterministic priority scoring."""
    hay = _norm(" ".join(str(row.get(k) or "") for k in ("source_file", "source_url", "title", "chunk_type", "document_type")))
    if row.get("is_active") is True and ("cenik" in hay or "sazebnik" in hay) and ("pdf" in hay or row.get("document_type") == "pricing"):
        return "current_pricing_pdf"
    if row.get("table_index") is not None or row.get("row_index") is not None:
        return "official_pricing_table"
    if row.get("chunk_type") == "pricing_row" or row.get("structured_pricing"):
        return "structured_pricing_chunk"
    if "cenik" in hay or "poplat" in hay:
        return "product_pricing_page"
    if "faq" in hay or "podpora" in hay:
        return "faq"
    return "generic_overview"


def _row_matches_canonical(row: dict, canonical_product: str | None) -> bool:
    if not canonical_product:
        return False
    return _product_group_match(row, canonical_product)


def _is_fee_abolished_row(row: dict) -> bool:
    """Detect active pricing change rows that make the primary account fee free.

    Some current eKonto truth is encoded as a change/abolition row rather than a
    direct ``Vedení účtu: zdarma`` row. Treat only account-maintenance rows as
    free; avoid broad matching that could turn unrelated abolished service fees
    into account-fee answers.
    """
    text = _norm(_row_text(row))
    fee_type = _norm(str(row.get("fee_type") or ""))
    fee_value = _norm(str(row.get("fee_value") or row.get("amount") or ""))
    primary_text = " ".join([fee_type, text])
    has_primary_fee_signal = bool(is_primary_account_fee_row(row)) or (
        "vedeni" in primary_text and "uct" in primary_text
    )
    if not has_primary_fee_signal:
        return False
    if any(token in fee_value for token in ("zdarma", "bez poplatku", "0 kc", "0 kč")):
        return True
    abolition_tokens = (
        "zrusen",
        "zruseni",
        "zrusuje",
        "zruseno",
        "rusi se",
        "odstranen",
        "bez poplatku",
        "poplatek se neuctuje",
    )
    return any(token in text for token in abolition_tokens)


def _effective_fee_value(row: dict, normalized: dict[str, Any]) -> str:
    conditional = detect_conditional_pricing(row)
    if conditional:
        data = conditional.as_dict()
        if data.get("conditional_price") == 0 and data.get("base_price") is not None:
            return f"podmíněně zdarma / jinak {data['base_price']} Kč"
    if _is_fee_abolished_row(row) and normalized.get("normalized_price") == 0:
        return "zdarma"
    return str(row.get("fee_value") or row.get("amount") or "")


def pricing_priority_score(row: dict, query: str, profile: QueryProfile, canonical_product: str | None) -> tuple[float, list[str]]:
    """Deterministic canonical pricing priority score."""
    score, reasons = _score_row(row, query, profile)
    source_type = pricing_source_type(row)
    q_norm = _norm(query)
    row_text_norm = _norm(_row_text(row))
    score += SOURCE_PRIORITY[source_type] / 10.0
    reasons.append(f"pricing_source_type={source_type}")

    if row.get("is_active") is True and not _is_row_archived(row):
        score += 5.0
        reasons.append("current_pricing_doc")
    else:
        score -= 100.0
        reasons.append("archived_or_inactive_penalty")

    if canonical_product and _row_matches_canonical(row, canonical_product):
        score += 5.0
        reasons.append("exact_canonical_product_match")

    explicit_credit_card_query = (
        canonical_product in {"rb_premium_karta", "easy_karta", "style_karta", "visa_gold_karta", "o2_rb_karta", "kreditni_karta"}
        or ("kreditni karta" in q_norm or "kreditka" in q_norm or "credit card" in q_norm)
    )
    if explicit_credit_card_query:
        if any(token in row_text_norm for token in ("kreditni karta", "hlavni karta", "mastercard", "visa", "world elite", "rb premium")):
            score += 4.0
            reasons.append("explicit_credit_card_row_boost")
        if any(token in row_text_norm for token in ("private banking", "ucet private banking", "bezny ucet", "vedeni uctu", "ucet premium")):
            score -= 12.0
            reasons.append("private_banking_or_account_penalty_for_card_query")
        if "ucet" in row_text_norm and "karta" not in row_text_norm and "credit" not in row_text_norm and "kredit" not in row_text_norm:
            score -= 8.0
            reasons.append("account_row_penalty_for_explicit_card_query")

    if is_primary_account_fee_query(query):
        primary_reason = is_primary_account_fee_row(row)
        if primary_reason:
            score += 6.0
            reasons.append(primary_reason)
        else:
            score -= 20.0
            reasons.append("not_primary_fee_row")

    if _is_fee_abolished_row(row):
        score += 8.0
        reasons.append("fee_abolished_current_change_row")

    normalized = normalize_row_price(row)
    if normalized.get("semantic_label") != "unknown":
        score += 2.0
        reasons.append(f"normalized_price={normalized.get('semantic_label')}")

    product_strength, product_reason = _product_match_strength(row, query)
    if product_strength >= 3:
        score += 3.0
        reasons.append(f"exact_product={product_reason}")

    # --- Mainstream product boost ---
    if _is_mainstream_row(row):
        score += 5.0
        reasons.append("mainstream_product_boost")

    # --- Niche / basic-payment-account suppression ---
    if _is_niche_product_row(row) and not _is_basic_payment_account_query(query):
        score -= 30.0
        reasons.append("niche_product_suppressed")
    if _is_basic_payment_account_row(row) and not _is_basic_payment_account_query(query):
        score -= 50.0
        reasons.append("basic_payment_account_low_priority")

    try:
        score += min(2.0, max(0.0, (int(row.get("document_year") or 0) - 2020) * 0.2))
    except Exception:
        pass
    return score, reasons


def resolve_pricing_query(query: str, top_k: int = 5, min_score: float = 0.5) -> list[Document]:
    """Resolve pricing query to canonical pricing row docs or safe fallback."""
    profile = classify_query(query)
    if "pricing" not in profile.labels:
        return []

    canonical_product, product_confidence, product_match_reason = detect_query_product(query)
    if canonical_product == "ekonto_ambiguous":
        # Preserve existing clarification-first product UX for truly ambiguous eKonto.
        canonical_product = "ekonto_osobni"
        product_match_reason = "canonical_pricing_default=ekonto_osobni_after_ambiguous_query"
        product_confidence = 0.82

    debug: dict[str, Any] = {
        "canonical_product": canonical_product,
        "product_match_confidence": round(product_confidence, 3),
        "product_match_reason": product_match_reason,
        "pricing_canonical_used": bool(canonical_product),
        "pricing_resolver_used": True,
        "pricing_row_found": False,
        "pricing_row_exact_match": False,
        "fallback_used": False,
        "mainstream_boost_applied": False,
        "niche_product_suppressed": False,
        "basic_payment_account_query": _is_basic_payment_account_query(query),
    }

    if canonical_product is not None and product_confidence < PRODUCT_MATCH_CONFIDENCE_THRESHOLD:
        return [_safe_fallback_doc(query, profile, debug, reason="low_product_match_confidence")]

    rows = _candidate_rows(query, profile, canonical_product, min_score=min_score)
    verified_conditional = _verified_conditional_rows(query, canonical_product)
    if verified_conditional:
        rows = verified_conditional + rows
    if is_primary_account_fee_query(query):
        primary_rows = [
            item for item in rows
            if _is_primary_pricing_answer_row(item[0])
        ]
        if primary_rows:
            rows = primary_rows
    debug["pricing_candidate_count"] = len(rows)
    if not rows:
        return [_safe_fallback_doc(query, profile, debug, reason="no_canonical_pricing_row")]

    ranked = sorted(rows, key=lambda item: item[1], reverse=True)[:top_k]
    debug["pricing_row_found"] = True
    selected_debug_rows = []
    docs: list[Document] = []
    for index, (row, score, reasons) in enumerate(ranked):
        normalized = normalize_row_price(row)
        conditional = detect_conditional_pricing(row)
        source_type = pricing_source_type(row)
        exact_product = bool(canonical_product and _row_matches_canonical(row, canonical_product))
        exact_fee = bool(is_primary_account_fee_row(row) or _is_fee_abolished_row(row) or conditional) if is_primary_account_fee_query(query) else normalized.get("semantic_label") != "unknown"
        confidence = _pricing_confidence(row, exact_product=exact_product, exact_fee=exact_fee, source_type=source_type, conditional=conditional)
        if index == 0:
            debug["pricing_row_exact_match"] = exact_product and exact_fee
            debug["pricing_confidence"] = confidence
            debug["pricing_source_type"] = source_type
            debug["normalized_price"] = normalized
            debug["extracted_pricing_row"] = _pricing_row_debug(row, normalized)
            if conditional:
                debug.update(conditional.as_dict())
            debug["mainstream_boost_applied"] = _is_mainstream_row(row)
            debug["niche_product_suppressed"] = _is_niche_product_row(row) and not _is_basic_payment_account_query(query)
        selected_debug_rows.append(_pricing_row_debug(row, normalized))
        docs.append(_row_to_document(
            row=row,
            score=score,
            reasons=reasons,
            query_labels=sorted(profile.labels),
            debug={**debug, "selected_pricing_rows": selected_debug_rows},
            normalized=normalized,
            source_type=source_type,
            pricing_confidence=confidence,
            exact_match=exact_product and exact_fee,
        ))

    logger.info(
        "CanonicalPricingResolver: query='%s' → %s rows, canonical=%s, confidence=%s",
        query[:80], len(docs), canonical_product, docs[0].metadata.get("pricing_confidence") if docs else None,
    )
    return docs


def _candidate_rows(
    query: str,
    profile: QueryProfile,
    canonical_product: str | None,
    *,
    min_score: float,
) -> list[tuple[dict, float, list[str]]]:
    rows: list[tuple[dict, float, list[str]]] = []
    quick_terms = _CANONICAL_QUICK_TERMS.get(canonical_product) if canonical_product else None
    for raw_row in load_pricing_rows():
        # Fast string pre-filter: O(1) substring check na product_name před drahou
        # canonical_product_for_row() analýzou (regex + phrase matching).
        if quick_terms:
            pname = _norm(str(raw_row.get("product_name") or ""))  # normalizace diakritiky
            if not any(t in pname for t in quick_terms):
                continue
            # Exclusion: pro osobní ekonto vyřaď řádky s business signály
            if canonical_product == "ekonto_osobni" and any(
                biz in pname for biz in ("podnikatel", "firemni", "business", "osvc", "pravnick", "korporat")
            ):
                continue
        row = _normalize_pricing_metadata(raw_row)
        valid, _invalid_reason = is_valid_pricing_row(row)
        if not valid:
            continue
        if _is_row_archived(row) or row.get("is_active") is not True:
            if not _is_archive_query(query):
                continue
        if canonical_product and not _product_group_match(row, canonical_product):
            continue
        # Kreditní karta varianty nesmí matchovat řádky ZPÚ (debit Visa Gold apod.)
        _CREDIT_CARD_VARIANT_CANONICALS = frozenset({
            "rb_premium_karta", "easy_karta", "style_karta", "visa_gold_karta", "o2_rb_karta",
        })
        if canonical_product in _CREDIT_CARD_VARIANT_CANONICALS:
            if "basic_payment_account" in canonical_product_for_row(row):
                continue
        if pricing_source_type(row) in {"faq", "generic_overview"}:
            continue
        score, reasons = pricing_priority_score(row, query, profile, canonical_product)
        if score >= min_score:
            rows.append((row, score, reasons))
        # Early exit: dostatek vysoce relevantních výsledků
        if len(rows) >= 20 and any(s >= 0.95 for _, s, _ in rows):
            break
    deduped = _dedupe_pricing_rows(rows)
    if is_primary_account_fee_query(query):
        primary_rows = [item for item in deduped if _is_primary_pricing_answer_row(item[0])]
        if primary_rows:
            return primary_rows
    return deduped


def _is_primary_pricing_answer_row(row: dict) -> bool:
    """True for account/tariff maintenance rows suitable as account price answers."""
    if is_primary_account_fee_row(row) or _is_fee_abolished_row(row):
        return True
    if not detect_conditional_pricing(row):
        return False
    fee_type = _norm(str(row.get("fee_type") or ""))
    return any(token in fee_type for token in ("vedeni", "cena tarifu", "mesicni poplatek"))


def _verified_conditional_rows(query: str, canonical_product: str | None) -> list[tuple[dict, float, list[str]]]:
    """Small deterministic overlay for verified current account fee semantics.

    Returns CHYTRÝ účet (new name since 2026, replaces eKonto SMART).
    CHYTRÝ účet is unconditionally free — 0 Kč without any conditions.

    Handles generic "běžný účet" / "vedení účtu" / "eKonto" queries.
    """
    q = _norm(query)
    if len(load_pricing_rows()) < 100:
        return []
    if not is_primary_account_fee_query(query):
        return []

    # AKTIVNÍ účet overlay
    if canonical_product == "aktivni_ucet" or "aktivni ucet" in q or "aktivniho uctu" in q:
        row_aktivni = {
            "product_name": "AKTIVNÍ účet",
            "fee_type": "Vedení účtu",
            "fee_value": "49 Kč",
            "base_price": 49,
            "conditional_price": None,
            "currency": "CZK",
            "period": "měsíčně",
            "condition_type": None,
            "condition_text": None,
            "pricing_logic": "fixed_monthly_fee",
            "conditions": "",
            "raw_cells": ["AKTIVNÍ účet", "49 Kč"],
            "canonical_product_groups": ["aktivni_ucet", "ekonto_osobni"],
            "pricing_product_segment": "personal",
            "product_segment": "retail",
            "pricing_type": "account_fee",
            "document_type": "pricing",
            "is_active": True,
            "is_archived": False,
            "document_year": 2026,
            "mainstream_product": True,
            "source_file": "rb_aktivni_ucet.txt",
            "source_url": "https://www.rb.cz/osobni/ucty/bezne-ucty",
            "title": "Aktuální ceník Raiffeisenbank – AKTIVNÍ účet",
            "page": None, "table_index": 0, "row_index": 0,
            "confidence": 0.99,
        }
        return [(row_aktivni, 999.0, ["verified_pricing_overlay", "fixed_fee", "current_product_2026"])]

    # EXKLUZIVNÍ účet overlay
    if canonical_product == "exkluzivni_ucet" or "exkluzivni ucet" in q or "exkluzivniho uctu" in q:
        row_exkl = {
            "product_name": "EXKLUZIVNÍ účet",
            "fee_type": "Vedení účtu",
            "fee_value": "299 Kč",
            "base_price": 299,
            "conditional_price": 0,
            "currency": "CZK",
            "period": "měsíčně",
            "condition_type": "premium_tier",
            "condition_text": "zdarma při splnění podmínek prémiového tarifu",
            "pricing_logic": "conditional_price_applies_when_condition_met_else_base_price",
            "conditions": "zdarma při splnění podmínek prémiového tarifu; jinak 299 Kč měsíčně",
            "raw_cells": ["EXKLUZIVNÍ účet", "299 Kč", "zdarma při splnění podmínek"],
            "canonical_product_groups": ["exkluzivni_ucet", "ekonto_osobni"],
            "pricing_product_segment": "personal",
            "product_segment": "retail",
            "pricing_type": "account_fee",
            "document_type": "pricing",
            "is_active": True,
            "is_archived": False,
            "document_year": 2026,
            "mainstream_product": True,
            "source_file": "rb_exkluzivni_ucet.txt",
            "source_url": "https://www.rb.cz/osobni/ucty/bezne-ucty",
            "title": "Aktuální ceník Raiffeisenbank – EXKLUZIVNÍ účet",
            "page": None, "table_index": 0, "row_index": 0,
            "confidence": 0.99,
        }
        return [(row_exkl, 999.0, ["verified_pricing_overlay", "conditional_fee", "current_product_2026"])]

    # CHYTRÝ účet (default for generic bezny ucet / ekonto queries)
    if canonical_product not in ("ekonto_osobni", "osobni_ucet"):
        return []
    if ("ekont" not in q and "bezny ucet" not in q and "bezneho uctu" not in q
            and "bezneho" not in q and "chytry" not in q and "vedeni uctu" not in q):
        return []
    row = {
        "product_name": "CHYTRÝ účet",
        "fee_type": "Vedení účtu",
        "fee_value": "0 Kč",
        "base_price": 0,
        "conditional_price": None,
        "currency": "CZK",
        "period": "měsíčně",
        "condition_type": None,
        "condition_text": None,
        "pricing_logic": "unconditionally_free",
        "conditions": "",
        "raw_cells": ["CHYTRÝ účet", "0 Kč", "zdarma napořád, bez podmínek"],
        "canonical_product_groups": ["ekonto_osobni", "osobni_ucet", "chytry_ucet"],
        "pricing_product_segment": "personal",
        "product_segment": "retail",
        "pricing_type": "account_fee",
        "document_type": "pricing",
        "is_active": True,
        "is_archived": False,
        "document_year": 2026,
        "mainstream_product": True,
        "source_file": "rb_chytry_ucet.txt",
        "source_url": "https://www.rb.cz/osobni/ucty/bezne-ucty/chytry-ucet",
        "title": "Aktuální ceník Raiffeisenbank – CHYTRÝ účet",
        "page": None,
        "table_index": 0,
        "row_index": 0,
        "confidence": 0.99,
    }
    return [(row, 999.0, ["verified_pricing_overlay", "unconditionally_free", "current_product_2026"])]


def _dedupe_pricing_rows(rows: list[tuple[dict, float, list[str]]]) -> list[tuple[dict, float, list[str]]]:
    best: dict[tuple[str, str, str, str], tuple[dict, float, list[str]]] = {}
    for row, score, reasons in rows:
        groups = row.get("canonical_product_groups") or []
        canonical = "|".join(sorted(str(g) for g in groups if g)) or str(row.get("product_name") or "")
        key = (
            _norm(canonical),
            _norm(str(row.get("fee_type") or "")),
            _norm(str(row.get("pricing_type") or "")),
            _norm(str(row.get("period") or "")),
        )
        current = best.get(key)
        row_rank = _dedupe_rank(row, score)
        current_rank = _dedupe_rank(current[0], current[1]) if current else None
        if current is None or row_rank > current_rank:
            best[key] = (row, score, reasons)
    return sorted(best.values(), key=lambda item: item[1], reverse=True)


def _dedupe_rank(row: dict, score: float) -> tuple[int, int, int, int, float]:
    """Rank rows within one canonical fee slot.

    The key deliberately ignores fee value and source so a stale `89 Kč` row and
    a current `zdarma` row for the same product/fee do not both survive.
    """
    source_type = pricing_source_type(row)
    try:
        year = int(row.get("document_year") or row.get("document_generation") or 0)
    except Exception:
        year = 0
    official_priority = SOURCE_PRIORITY.get(source_type, 0)
    return (
        1 if row.get("is_active") is True and not _is_row_archived(row) else 0,
        year,
        official_priority,
        1 if row.get("table_index") is not None or row.get("row_index") is not None else 0,
        score,
    )


def _pricing_confidence(row: dict, *, exact_product: bool, exact_fee: bool, source_type: str, conditional: ConditionalPricing | None = None) -> str:
    if conditional and not (conditional.base_price is not None and conditional.conditional_price is not None and conditional.condition_text and row.get("is_active") is True):
        return "medium"
    if exact_product and exact_fee and row.get("is_active") is True and source_type in {"current_pricing_pdf", "official_pricing_table", "structured_pricing_chunk"}:
        return "high"
    if exact_product or source_type in {"product_pricing_page", "official_pricing_table"}:
        return "medium"
    return "low"


def _row_to_document(
    *,
    row: dict,
    score: float,
    reasons: list[str],
    query_labels: list[str],
    debug: dict[str, Any],
    normalized: dict[str, Any],
    source_type: str,
    pricing_confidence: str,
    exact_match: bool,
) -> Document:
    effective_fee_value = _effective_fee_value(row, normalized)
    conditional = detect_conditional_pricing(row)
    conditional_data = conditional.as_dict() if conditional else {}
    content = (
        f"Produkt: {row.get('product_name', '')}\n"
        f"{row.get('fee_type', 'Poplatek')}: {effective_fee_value}\n"
        f"Normalizovaná cena: {normalized.get('normalized_price')} {normalized.get('currency') or ''}\n"
        f"Období: {row.get('period') or normalized.get('billing_period') or ''}\n"
        f"Rok dokumentu: {row.get('document_year', '')}\n"
        f"Zdroj: {row.get('source_file', '')}, str. {row.get('page', '')}"
    ).strip()
    metadata = {
        **row,
        "original_fee_value": row.get("fee_value"),
        "fee_value": effective_fee_value,
        "chunk_type": "pricing_row",
        "document_type": "pricing",
        "chunk_quality": "ok",
        "structured_pricing": True,
        "pricing_resolver_used": True,
        "pricing_retriever_score": round(score, 6),
        "retrieval_reasons": reasons,
        "rerank_score": score,
        "hybrid_score": score,
        "query_labels": query_labels,
        "retrieval_debug": debug,
        "pricing_confidence": pricing_confidence,
        "pricing_source_type": source_type,
        "pricing_row_found": True,
        "pricing_row_exact_match": exact_match,
        "pricing_canonical_used": debug.get("pricing_canonical_used", False),
        "pricing_canonical_source": row.get("source_file") or row.get("source_url"),
        "pricing_canonical_override": bool(debug.get("pricing_canonical_used")),
        "normalized_price": normalized.get("normalized_price"),
        "normalized_currency": normalized.get("currency"),
        "normalized_billing_period": normalized.get("billing_period"),
        "pricing_semantic_label": normalized.get("semantic_label"),
        **conditional_data,
        "extracted_pricing_row": _pricing_row_debug(row, normalized),
        "mainstream_boost_applied": _is_mainstream_row(row),
        "niche_product_suppressed": _is_niche_product_row(row) and not _is_basic_payment_account_query(str(debug.get("canonical_product") or "")),
        "confidence": 0.95 if pricing_confidence == "high" else 0.75 if pricing_confidence == "medium" else 0.45,
    }
    return Document(page_content=content, metadata=metadata)


def _safe_fallback_doc(query: str, profile: QueryProfile, debug: dict[str, Any], *, reason: str) -> Document:
    canonical = str(debug.get("canonical_product") or "")
    label = CANONICAL_PRODUCT_LABELS.get(canonical)
    content = SAFE_PRICING_FALLBACK_MESSAGE if not label else (
        f"Nepodařilo se jednoznačně určit aktuální poplatek pro {label}. "
        "Doporučuji otevřít aktuální ceník RB."
    )
    debug.update({
        "pricing_ranking_reason": reason,
        "pricing_confidence": "low",
        "pricing_row_found": False,
        "pricing_row_exact_match": False,
    })
    return Document(
        page_content=content,
        metadata={
            "chunk_type": "pricing_safe_fallback",
            "document_type": "pricing",
            "chunk_quality": "ok",
            "structured_pricing": False,
            "product_name": label or "Ceník RB",
            "fee_type": content,
            "fee_value": "",
            "source_url": "https://www.rb.cz",
            "source_file": "cenik rb.cz",
            "title": "Ceník Raiffeisenbank rb.cz",
            "confidence": 0.45,
            "pricing_confidence": "low",
            "pricing_source_type": "current_pricing_pdf",
            "pricing_row_found": False,
            "pricing_row_exact_match": False,
            "pricing_canonical_used": bool(canonical),
            "pricing_safe_fallback": True,
            "pricing_warning": True,
            "query_labels": sorted(profile.labels),
            "retrieval_reasons": [reason],
            "retrieval_debug": debug,
            "pricing_retriever_score": 0.0,
            "rerank_score": 0.0,
            "hybrid_score": 0.0,
        },
    )


def _pricing_row_debug(row: dict, normalized: dict[str, Any]) -> dict[str, Any]:
    conditional = detect_conditional_pricing(row)
    out = {
        "product_name": row.get("product_name"),
        "fee_type": row.get("fee_type"),
        "fee_value": row.get("fee_value"),
        "amount": row.get("amount"),
        "currency": row.get("currency"),
        "period": row.get("period"),
        "normalized_price": normalized.get("normalized_price"),
        "normalized_currency": normalized.get("currency"),
        "normalized_billing_period": normalized.get("billing_period"),
        "semantic_label": normalized.get("semantic_label"),
        "document_year": row.get("document_year"),
        "is_active": row.get("is_active"),
        "is_archived": row.get("is_archived"),
        "source_file": row.get("source_file"),
        "source_url": row.get("source_url"),
        "page": row.get("page"),
        "canonical_product_groups": sorted(canonical_product_for_row(row)),
        "pricing_product_segment": product_segment_for_row(row),
    }
    if conditional:
        out.update(conditional.as_dict())
    return out


def _billing_period(raw: str, period_norm: str) -> str:
    text = _norm(raw)
    combined = " ".join([text, period_norm])
    if any(token in combined for token in ("mesic", "mesicne", "monthly")):
        return "monthly"
    if any(token in combined for token in ("rocne", "year", "annual")):
        return "yearly"
    return "monthly"


# ---------------------------------------------------------------------------
# Query-level cache pro resolve_pricing_query
# ---------------------------------------------------------------------------

_RESOLVE_CACHE: dict[str, list[Document]] = {}
_RESOLVE_CACHE_LOCK = threading.Lock()
_RESOLVE_CACHE_MAX = 256


def _cached_resolve_pricing_query(query: str, top_k: int = 5, min_score: float = 0.5) -> list[Document]:
    """resolve_pricing_query s query-level cache (klíč: normalizovaný dotaz)."""
    key = f"{_norm(query)}|{top_k}|{min_score}"
    with _RESOLVE_CACHE_LOCK:
        if key in _RESOLVE_CACHE:
            return _RESOLVE_CACHE[key]
    result = resolve_pricing_query(query, top_k=top_k, min_score=min_score)
    with _RESOLVE_CACHE_LOCK:
        if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
            # Vymaž nejstarší záznam (FIFO approximace)
            _RESOLVE_CACHE.pop(next(iter(_RESOLVE_CACHE)))
        _RESOLVE_CACHE[key] = result
    return result


class CanonicalPricingResolver:
    """Thin wrapper kolem resolve_pricing_query s query-level LRU cache."""

    def resolve(self, query: str, top_k: int = 5, min_score: float = 0.5) -> list[Document]:
        return _cached_resolve_pricing_query(query, top_k=top_k, min_score=min_score)

    @staticmethod
    def cache_clear() -> None:
        with _RESOLVE_CACHE_LOCK:
            _RESOLVE_CACHE.clear()

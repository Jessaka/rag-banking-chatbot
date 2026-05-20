"""Deterministic structured pricing retrieval over JSONL rows.

No embeddings, no reranker. This is used for pricing/account fee queries where
exact structured rows are safer than LLM synthesis over large table chunks.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

import config
from src.retrieval.query_classifier import BUSINESS_ACCOUNT_TERMS, PERSONAL_ACCOUNT_TERMS, QueryProfile, classify_query, expand_query
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _norm(text: str) -> str:
    text = text.lower()
    repl = str.maketrans("áčďéěíňóřšťúůýž", "acdeeinorstuuyz")
    return text.translate(repl)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[\wÀ-ɏ]+", _norm(text)) if len(t) > 1}


@lru_cache(maxsize=1)
def load_pricing_rows(path: str | Path | None = None) -> list[dict]:
    path = Path(path or config.PRICING_ROWS_PATH)
    if not path.exists():
        logger.warning(f"Structured pricing rows nenalezeny: {path}")
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    logger.info(f"Structured pricing rows loaded: {len(rows)} z {path}")
    return rows


def _row_text(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in (
        "product_name", "fee_type", "fee_value", "currency", "period", "conditions", "title", "source_file", "category", "pricing_type"
    ))


# Normalized stems of non-account-fee fee_type terms that MUST be hard-excluded.
# Checked BEFORE any scoring to prevent mortgage/loan/card/overdraft rows
# from reaching the answer formatter even when they have token overlap.
_FEE_EXCLUDE_STEMS: frozenset[str] = frozenset({
    "oceneni",        # ocenění (property valuation)
    "nemovitost",     # nemovitost (real estate)
    "rezerv",         # rezervace, rezervaci, rezervy (reservation, overdraft)
    "bezuroc",        # bezúročná, bezúročný (interest-free -> overdraft)
    "cerpan",         # čerpání, čerpat (drawing/pulling from loan)
    "uver",           # úvěr, úvěru (loan)
    "hypotek",        # hypotéka, hypoteční (mortgage)
    "kart",           # karta, karty (card)
    "hotovost",       # hotovost (cash)
    "vklad",          # vklad (deposit)
    "vyber",          # výběr, výběry (withdrawal)
    "transakc",       # transakce (transaction)
    "pojist",         # pojištění (insurance)
    "spor",           # spoření, spořicí (savings)
    "penzijn",        # penzijní (pension)
    "stavebn",        # stavební (building savings)
})

# ---------------------------------------------------------------------------
# Primary account fee – ultra-precise row detection
# ---------------------------------------------------------------------------

# Substrings (in normalized fee_type) that disqualify a row from being a
# primary account fee.  These catch multicurrency add-ons, MEK/OEk, BIU,
# transaction fees, cash ops, card fees, insurance, etc.
_PRIMARY_FEE_EXCLUDE_SUBSTRINGS: frozenset[str] = frozenset({
    "vedlejsi",       # vedlejší měnové složky
    "menove",         # měnové složky
    "elektronicky",   # elektronický klíč (OEk)
    "elektronickeho", # elektronického klíče
    "mobilni",        # mobilní elektronický klíč (MEK)
    "investicni",     # investiční účet (BIU)
    "uhrada",         # úhrada (payment)
    "uhrady",         # úhrady
    "platba",         # platba
    "prikaz",         # platební příkaz
    "import",         # import plateb
    "hromadny",       # hromadné platby
    "pronajem",       # pronájem
    "bezpecnostni",   # bezpečnostní schránka
    "vyzva",          # výzva k zaplacení
    "dluh",           # dluh
    "nestandardni",   # nestandardní služby
    "vypis",          # výpis
    "vypisu",         # výpisu
    "potvrzeni",       # potvrzení
    "sprava",         # správa služby
    "spravy",         # správy služby
    "nastaveni",      # nastavení služby
})


def is_primary_account_fee_row(row: dict) -> bool:
    """Return True if *row* is a **primary** account-fee row.

    A primary account fee row covers only the core monthly account
    maintenance fee – i.e. fee_types such as:

    * ``vedení (běžného) účtu``
    * ``cena tarifu``
    * ``poplatek za vedení``
    * ``měsíční poplatek`` (za účet)

    Everything else (multicurrency add-ons, MEK, BIU, transaction
    fees, cash ops, card fees, …) is rejected.
    """
    ft = _norm(str(row.get("fee_type") or ""))
    if not ft:
        return False

    # --- HARD EXCLUDE ---
    # If the normalized fee_type contains ANY exclude substring it is NOT
    # a primary row, regardless of token-level allow patterns.
    for excl in _PRIMARY_FEE_EXCLUDE_SUBSTRINGS:
        if excl in ft:
            return False

    ft_tokens = {t for t in re.findall(r"[\wÀ-ɏ]+", ft) if len(t) > 1}

    # --- ALLOW patterns (token-level) ---
    # 1. vedení … účtu  (primary account maintenance)
    if "vedeni" in ft_tokens and "uctu" in ft_tokens:
        return True
    # 2. cena tarifu     (active retail accounts)
    if "cena" in ft_tokens and "tarifu" in ft_tokens:
        return True
    # 3. poplatek za vedení
    if "poplatek" in ft_tokens and "vedeni" in ft_tokens:
        return True
    # 4. měsíční poplatek
    if "mesicni" in ft_tokens and "poplatek" in ft_tokens:
        return True
    # 5. English patterns
    ft_lower = str(row.get("fee_type", "")).lower()
    if "account" in ft_lower and "maintenance" in ft_lower:
        return True
    if "monthly" in ft_lower and "account" in ft_lower and "fee" in ft_lower:
        return True

    return False


# Normalized triggers for primary-account-fee queries.
# A broader general-pricing query (e.g. "poplatek za výběr z bankomatu")
# MUST NOT activate the primary filter.
_PRIMARY_QUERY_CORE_TERMS: frozenset[str] = frozenset({
    "vedeni", "uctu", "ucet", "bezneho", "mesicni", "poplatek",
})


def is_primary_account_fee_query(query: str) -> bool:
    """Return True when *query* is explicitly about primary account fees.

    Triggers:
    * ``vedení … účtu`` anywhere in the query
    * ``měsíční poplatek (za) účet``
    * English ``account maintenance`` / ``monthly account fee``
    """
    q = _norm(query)
    qt = {t for t in re.findall(r"[\wÀ-ɏ]+", q) if len(t) > 1}

    # vedení … účtu  (strongest single signal)
    if "vedeni" in qt and "uctu" in qt:
        return True
    # měsíční poplatek  (buy signals: "měsíční poplatek za eKonto",
    # "měsíční poplatek za účet", "měsíční poplatek")
    if "mesicni" in qt and "poplatek" in qt:
        return True
    # English
    q_lower = query.lower()
    if "account" in q_lower and "maintenance" in q_lower:
        return True
    if "monthly" in q_lower and "account" in q_lower and "fee" in q_lower:
        return True

    return False


def _score_row(row: dict, query: str, profile: QueryProfile) -> tuple[float, list[str]]:
    q_norm = _norm(expand_query(query, profile))
    text = _norm(_row_text(row))

    # --- HARD EXCLUDE based on fee_type ---
    # If the row's fee_type contains a known non-account-fee stem, block it
    # completely regardless of token overlap or other scoring signals.
    fee_type_norm = _norm(str(row.get("fee_type") or ""))
    for stem in _FEE_EXCLUDE_STEMS:
        if stem in fee_type_norm:
            return -999.0, [f"hard_excluded_fee_type={stem}"]

    q_tokens = _tokens(q_norm)
    row_tokens = _tokens(text)
    overlap = len(q_tokens & row_tokens)
    score = overlap * 0.08
    reasons = [f"token_overlap={overlap}"]

    try:
        confidence = float(row.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    if confidence < 0.70:
        return -999.0, [f"low_confidence={confidence:.2f}"]

    if not row.get("fee_value"):
        score -= 1.0; reasons.append("missing_fee_value")
    if "ekonto" in q_norm and "ekonto" in text:
        score += 1.2; reasons.append("ekonto exact")
    if (q_tokens & {"vedeni", "ucet", "uctu"}) and (row_tokens & {"vedeni", "cena", "poplatek", "ucet"}):
        score += 0.6; reasons.append("account fee intent")
    fee_tokens = _tokens(str(row.get("fee_type") or ""))
    if "vedeni" in q_norm and not (fee_tokens & {"vedeni", "cena", "poplatek"}):
        score -= 0.5; reasons.append("non-account-fee wording penalty")
    if "personal_retail_account" in profile.labels:
        if row.get("category") == "retail" or "cenik-pi" in text:
            score += 0.5; reasons.append("retail preferred")
        if any(_norm(t) in text for t in BUSINESS_ACCOUNT_TERMS) or row.get("category") == "corporate":
            score -= 0.8; reasons.append("business penalty")
    if row.get("pricing_type") == "account_fee":
        score += 0.3; reasons.append("account_fee")
    if "zdarma" in text and "zdarma" in q_norm:
        score += 0.2; reasons.append("free match")
    return score, reasons


# ---------------------------------------------------------------------------
# Hard filter – archived/discontinued rows
# ---------------------------------------------------------------------------

_ARCHIVE_KEYWORDS_RAW = frozenset({
    "historický", "historický", "historické",
    "archiv", "archivní",
    "již nenabízen", "již nenabízený",
    "starý produkt", "staré produkty",
    "nenabízený",
})
# Pre-normalized variants (no diacritics) so _is_archive_query doesn't
# have to re-normalize every keyword on every call.
_ARCHIVE_KEYWORDS: frozenset[str] = frozenset(
    word
    for kw in _ARCHIVE_KEYWORDS_RAW
    for word in (kw, _norm(kw))
)


def _is_archive_query(query: str) -> bool:
    """True if the user explicitly asks about archived/discontinued products."""
    q = _norm(query)
    return any(kw in q for kw in _ARCHIVE_KEYWORDS)


def _is_row_archived(row: dict) -> bool:
    """Check if a pricing row belongs to an archived/discontinued product."""
    val = row.get("is_archived")
    if val in (True, "True", "true", 1, "1"):
        return True
    val = row.get("is_discontinued")
    if val in (True, "True", "true", 1, "1"):
        return True
    title = _norm(row.get("title", ""))
    if "již nenabízen" in title or "jiz nenabiz" in title:
        return True
    return False


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------

def pricing_search(query: str, top_k: int = 5, min_score: float = 0.5) -> list[Document]:
    profile = classify_query(query)
    if "pricing" not in profile.labels:
        return []
    scored: list[tuple[dict, float, list[str]]] = []
    for row in load_pricing_rows():
        score, reasons = _score_row(row, query, profile)
        if score >= min_score:
            scored.append((row, score, reasons))

    # --- Primary account fee filter -----------------------------------------
    # If the user explicitly asks about *primary* account fees, restrict to
    # primary rows only.  Non-primary rows (multicurrency, MEK, BIU, card,
    # etc.) are dropped BEFORE archive filtering so that archived primary
    # rows can still be shown as a last resort.
    debug: dict[str, str | int] = {}
    primary_rows: list[tuple[dict, float, list[str]]] = []
    if is_primary_account_fee_query(query):
        primary_rows = [(r, s, rs) for r, s, rs in scored if is_primary_account_fee_row(r)]
        debug["primary_account_fee_filter"] = "true"
        debug["primary_rows"] = len(primary_rows)
        if primary_rows:
            scored = primary_rows
            logger.info(f"Primary account fee filter: {len(primary_rows)} primary rows")
        else:
            debug["primary_fallback"] = "true"
            logger.info("Primary account fee filter: 0 primary rows → fallback to general scoring")

    # --- Archive filter ------------------------------------------------------
    filter_reason: str | None = None
    if not _is_archive_query(query):
        active = [(r, s, rs) for r, s, rs in scored if not _is_row_archived(r)]
        if active:
            filtered = len(scored) - len(active)
            if filtered > 0:
                filter_reason = f"archived_hard_filtered:{filtered}"
                logger.info(f"PricingRetriever hard filter odstranil {filtered} archived rows")
                # If this is a primary-filtered set and we lost all primary rows,
                # signal the fallback.
                if primary_rows and not any(True for _ in active):
                    debug["primary_archived_fallback"] = "true"
            scored = active
        else:
            fbk = "archived_hard_filter_fallback:"
            if primary_rows:
                fbk += "all_primary_rows_archived"
                debug["primary_archived_fallback"] = "true"
            else:
                fbk += "all_rows_archived"
            filter_reason = fbk
            logger.warning(f"PricingRetriever: vše by bylo odfiltrováno → fallback na všechny řádky")

    # --- Rank & build docs ---------------------------------------------------
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]
    docs: list[Document] = []
    for row, score, reasons in ranked:
        content = (
            f"Produkt: {row.get('product_name', '')}\n"
            f"{row.get('fee_type', 'Poplatek')}: {row.get('fee_value', '')}\n"
            f"Měna: {row.get('currency', '')}\n"
            f"Období: {row.get('period', '')}\n"
            f"Podmínky: {row.get('conditions', '')}\n"
            f"Zdroj: {row.get('source_file', '')}, str. {row.get('page', '')}"
        ).strip()
        meta: dict = {
            **row,
            "chunk_type": "pricing_row",
            "document_type": "pricing",
            "chunk_quality": "ok",
            "structured_pricing": True,
            "pricing_retriever_score": round(score, 6),
            "retrieval_reasons": reasons,
            "rerank_score": score,
            "hybrid_score": score,
            "query_labels": sorted(profile.labels),
            "retrieval_debug": debug,
        }
        if filter_reason:
            meta["structured_pricing_filter_reason"] = filter_reason
        docs.append(Document(page_content=content, metadata=meta))
    logger.info(f"PricingRetriever: query='{query[:60]}' → {len(docs)} structured rows")
    return docs

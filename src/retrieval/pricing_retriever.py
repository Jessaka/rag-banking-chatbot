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
# transaction fees, cash ops, card fees, insurance, service fees,
# notifications, etc.
_PRIMARY_FEE_EXCLUDE_SUBSTRINGS: frozenset[str] = frozenset({
    "vedlejsi",         # vedlejší měnové složky / vedlejší složka
    "menove",           # měnové složky
    "elektronicky",     # elektronický klíč (OEk)
    "elektronickeho",   # elektronického klíče
    "mobilni",          # mobilní elektronický klíč (MEK)
    "investicni",       # investiční účet (BIU)
    "uhrada",           # úhrada (payment)
    "uhrady",           # úhrady
    "platba",           # platba
    "prikaz",           # platební příkaz
    "import",           # import plateb
    "hromadny",         # hromadné platby
    "pronajem",         # pronájem
    "bezpecnostni",     # bezpečnostní schránka
    "vyzva",            # výzva k zaplacení
    "dluh",             # dluh
    "nestandardni",     # nestandardní služby
    "vypis",            # výpis
    "vypisu",           # výpisu
    "potvrzeni",        # potvrzení
    "sprava",           # správa služby
    "spravy",           # správy služby
    "nastaveni",        # nastavení služby
    # --- Nové excludy ze service/config kategorie ---
    "notifikac",        # notifikace, notifikaci
    "telefon",          # telefonní bankovnictví
    "sms",              # SMS notifikace
    "informuj",         # informuj mě (služba)
    "rb klic",          # RB klíč
    "rbklic",           # RBklíč (bez mezery)
    "doplnkov",         # doplňkové služby
    "doplnkove",        # doplňkové služby
    "balicek sluzeb",   # balíček služeb
    "multicurrency",    # multicurrency (anglicky)
})

# Strict allow patterns for primary fee_type TOKENS.
# A row MUST match at least one of these to be considered primary.
_PRIMARY_FEE_ALLOW_TOKEN_SETS: frozenset[frozenset[str]] = frozenset({
    frozenset({"vedeni", "uctu"}),              # vedení … účtu
    frozenset({"vedeni", "bezneho", "uctu"}),   # vedení jednoho běžného účtu
    frozenset({"cena", "tarifu"}),               # cena tarifu
    frozenset({"poplatek", "vedeni"}),           # poplatek za vedení
    frozenset({"mesicni", "poplatek"}),          # měsíční poplatek
})


def is_primary_account_fee_row(row: dict) -> str | None:
    """Check if *row* is a **primary** account-fee row.

    Returns:
        A string *reason* why the row is considered primary, or ``None``
        if the row should be excluded from primary account fee results.
    """
    ft = _norm(str(row.get("fee_type") or ""))
    if not ft:
        return None

    # --- HARD EXCLUDE (substring) ---
    for excl in _PRIMARY_FEE_EXCLUDE_SUBSTRINGS:
        if excl in ft:
            return None

    ft_tokens = {t for t in re.findall(r"[\wÀ-ɏ]+", ft) if len(t) > 1}

    # --- ALLOW (strict token-set intersection) ---
    for token_set in _PRIMARY_FEE_ALLOW_TOKEN_SETS:
        if token_set.issubset(ft_tokens):
            return f"primary_fee_type={ft}"

    # --- English allow patterns ---
    ft_lower = str(row.get("fee_type", "")).lower()
    if "account" in ft_lower and "maintenance" in ft_lower:
        return "primary_fee_type=account maintenance"
    if "monthly" in ft_lower and "account" in ft_lower and "fee" in ft_lower:
        return "primary_fee_type=monthly account fee"

    return None


def is_primary_account_fee_query(query: str) -> bool:
    """Return True when *query* is explicitly about primary account fees.

    Triggers:
    * ``vedení`` anywhere (alone – strong signal in banking context)
    * ``vedení … účtu``
    * ``měsíční poplatek (za) účet``
    * ``stojí účet``, ``cena (za) účet``
    * English ``account maintenance`` / ``monthly account fee`` / ``monthly fee``
    """
    q = _norm(query)
    qt = {t for t in re.findall(r"[\wÀ-ɏ]+", q) if len(t) > 1}

    # --- Czech primary signals ---
    # "vedení" alone – strongest single signal.
    # Catches "Kolik stojí vedení eKonta?", "poplatek za vedení", etc.
    if "vedeni" in qt:
        return True
    # "stojí" + "účet" → "Kolik stojí účet?", "cena účtu", "stojí vedení účtu"
    if "stoji" in qt and "ucet" in qt:
        return True
    # "měsíční poplatek" → "měsíční poplatek za eKonto", "měsíční poplatek za účet"
    if "mesicni" in qt and "poplatek" in qt:
        return True

    # --- English signals ---
    q_lower = query.lower()
    if "account" in q_lower and "maintenance" in q_lower:
        return True
    if "monthly" in q_lower and "account" in q_lower and "fee" in q_lower:
        return True
    if "monthly" in q_lower and "fee" in q_lower:
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
    all_scored: list[tuple[dict, float, list[str]]] = []
    for row in load_pricing_rows():
        score, reasons = _score_row(row, query, profile)
        if score >= min_score:
            all_scored.append((row, score, reasons))

    debug: dict[str, str | int] = {}

    # --- Active / archived split --------------------------------------------
    active_scored = [(r, s, rs) for r, s, rs in all_scored if not _is_row_archived(r)]
    archived_scored = [(r, s, rs) for r, s, rs in all_scored if _is_row_archived(r)]

    debug["active_rows_count"] = len(active_scored)
    debug["archived_rows_count"] = len(archived_scored)

    # --- Helper: apply primary filter to a set ------------------------------
    def _filter_primary(rows: list[tuple[dict, float, list[str]]]) -> tuple[list[tuple[dict, float, list[str]]], list[str]]:
        """Return only primary account fee rows when the query asks for them.

        Returns:
            (filtered_rows, primary_fee_reasons)
        """
        reasons: list[str] = []
        if is_primary_account_fee_query(query):
            filtered: list[tuple[dict, float, list[str]]] = []
            for r, s, rs in rows:
                reason = is_primary_account_fee_row(r)
                if reason is not None:
                    filtered.append((r, s, rs))
                    reasons.append(reason)
                else:
                    ft = _norm(str(r.get("fee_type", "")))
                    reasons.append(f"excluded_fee_type={ft}" if ft else "excluded_no_fee_type")
            if filtered:
                debug["primary_account_fee_filter"] = "true"
                debug["primary_rows"] = len(filtered)
                debug["primary_fee_reason"] = "; ".join(reasons[:20])
                return filtered, reasons
            else:
                debug["primary_fallback"] = "true"
                debug["primary_fee_excluded_all"] = "; ".join(reasons[:20])
        return rows, reasons

    # --- Phase 1: select best candidate set ----------------------------------
    # Priority (for non-archive queries):
    #   A. active + primary  (most precise)
    #   B. archived + primary (precise, but archived – shown only when no
    #      active primary rows exist)
    #   C. active general     (imprecise but active)
    #   D. archived general   (last resort)

    if _is_archive_query(query):
        # User explicitly asked for archived → use everything
        candidate = all_scored
    else:
        is_primary = is_primary_account_fee_query(query)

        # Priority A: active + primary
        candidate, _ = _filter_primary(active_scored)
        if is_primary and debug.get("primary_account_fee_filter"):
            debug["active_results_count"] = len(candidate)
            logger.info(f"Active-primary: {len(candidate)} rows")
        # Priority B: archived + primary (only when A produced nothing)
        elif is_primary and not debug.get("primary_account_fee_filter"):
            candidate, _ = _filter_primary(archived_scored)
            if debug.get("primary_account_fee_filter"):
                debug["archived_fallback_used"] = "true"
                debug["primary_rows"] = len(candidate)
                logger.info(f"Archived-primary fallback: {len(candidate)} rows")
            else:
                # Priority C: active general (no primary at all)
                candidate = active_scored or archived_scored
                debug["active_results_count"] = len(candidate)
                logger.info(f"General fallback (no primary): {len(candidate)} rows")
        else:
            # Non-primary query: active first, archived fallback
            candidate = active_scored or archived_scored
            if not active_scored and archived_scored:
                debug["archived_fallback_used"] = "true"
            debug["active_results_count"] = len(candidate)
            logger.info(
                f"{'Active' if active_scored else 'Archived'}-first: {len(candidate)} rows"
            )

    # --- Rank & build docs ---------------------------------------------------
    ranked = sorted(candidate, key=lambda item: item[1], reverse=True)[:top_k]
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
        docs.append(Document(page_content=content, metadata=meta))
    logger.info(f"PricingRetriever: query='{query[:60]}' → {len(docs)} structured rows")
    return docs

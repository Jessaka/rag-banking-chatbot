"""Deterministic structured pricing retrieval over JSONL rows.

No embeddings, no reranker. This is used for pricing/account fee queries where
exact structured rows are safer than LLM synthesis over large table chunks.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

import config
from src.ingestion.quality_filters import is_valid_pricing_row
from src.retrieval.query_classifier import BUSINESS_ACCOUNT_TERMS, PERSONAL_ACCOUNT_TERMS, QueryProfile, classify_query, expand_query
from src.utils.logger import get_logger

logger = get_logger(__name__)

PRODUCT_MATCH_CONFIDENCE_THRESHOLD = 0.75
NO_UNAMBIGUOUS_PRICING_MESSAGE = "Nepodařilo se najít jednoznačný aktuální ceník pro daný produkt."
EKONTO_CLARIFICATION_MESSAGE = "Upřesněte prosím, jestli myslíte osobní eKonto, nebo podnikatelské eKonto."
CANONICAL_PRODUCT_LABELS = {
    "kreditni_karta": "kreditní karta",
    "debetni_karta": "debetní karta",
    "hypoteky": "hypotéku / nemovitost",
    "pujcky": "půjčku / úvěr",
    "sporeni": "spoření",
    "investice": "investice",
    "sepa_swift": "SEPA/SWIFT platbu",
    "apple_google_pay": "Apple Pay / Google Pay",
    "ekonto_osobni": "osobní eKonto",
    "ekonto_podnikatelske": "podnikatelské eKonto",
    "basic_payment_account": "Základní platební účet",
}


def _norm(text: str) -> str:
    text = text.lower()
    repl = str.maketrans("áčďéěíňóřšťúůýž", "acdeeinorstuuyz")
    return text.translate(repl)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[\wÀ-ɏ]+", _norm(text)) if len(t) > 1}


@lru_cache(maxsize=1)
@lru_cache(maxsize=4)
def _load_pricing_rows_from_path(path_str: str) -> tuple[dict, ...]:
    """Načte a cachuje pricing rows ze souboru. Tuple je hashable pro lru_cache."""
    path = Path(path_str)
    if not path.exists():
        logger.warning(f"Structured pricing rows nenalezeny: {path}")
        return ()
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    logger.info(f"Structured pricing rows loaded: {len(rows)} z {path}")
    return tuple(rows)


def load_pricing_rows(path: str | Path | None = None) -> list[dict]:
    path_str = str(path or config.PRICING_ROWS_PATH)
    return list(_load_pricing_rows_from_path(path_str))


# Expose cache_clear so tests can invalidate between test cases
load_pricing_rows.cache_clear = _load_pricing_rows_from_path.cache_clear  # type: ignore[attr-defined]


def _row_text(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in (
        "product_name", "fee_type", "fee_value", "currency", "period", "conditions", "title", "source_file", "category", "pricing_type"
    ))


# Canonical product/entity matching is intentionally retrieval-time only: the
# JSONL/Qdrant index can stay untouched while we make pricing answers safer.
_QUERY_PRODUCT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ekonto_osobni": ("osobni ekonto", "soukrome ekonto", "ekonto osobni", "ekonto pro osobni pouziti"),
    "ekonto_podnikatelske": (
        "podnikatelske ekonto", "podnikatelsky ekonto", "ekonto podnikatelske",
        "business ekonto", "ekonto pro podnikatele", "ekonto osvc",
        "podnikatelskeho ekonta",
    ),
    "podnikatelsky_ucet": (
        "podnikatelsky ucet", "podnikatelske konto", "podnikatelske ekonto",
        "business ucet", "ucet pro podnikatele", "podnikatele", "osvc",
        "podnikatelskeho uctu",
    ),
    "firemni_ucet": ("firemni ucet", "ucet pro firmu", "firemni konto", "firmy", "firma", "pravnicke osoby", "firemniho uctu"),
    "kreditni_karta": ("kreditni karta", "kreditni karty", "kreditni kartu", "kreditni kartou", "kreditni karte", "kreditka", "credit card"),
    "debetni_karta": ("debetni karta", "debetni karty", "debetni kartu", "debetni kartou", "debitni karta", "debitni karty", "debetka", "debit card"),
    "hypoteky": ("hypoteka", "hypotecni", "hypoteky"),
    "pujcky": ("pujcka", "pujcky", "uver", "uvery", "spotrebitelsky uver"),
    "sporeni": ("sporeni", "sporici ucet", "sporici", "terminovany vklad"),
    "investice": ("investice", "investicni", "fond", "fondy", "dluhopis", "akcie"),
    "sepa_swift": ("sepa", "swift", "zahranicni platba", "zahranicni platby", "eur platba"),
    "apple_google_pay": ("apple pay", "google pay", "mobilni platby", "placeni mobilem"),
    "osobni_ucet": ("bezny ucet", "bezneho uctu", "bezneho ucetu", "osobni ucet", "soukromy ucet", "ucet pro osobni pouziti"),
    "basic_payment_account": ("zakladni platebni ucet", "zakladniho platebniho uctu", "social ucet", "chraneny ucet"),
}

_ROW_PRODUCT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ekonto_osobni": ("ekonto", "e konto", "e-konto"),
    "ekonto_podnikatelske": ("podnikatelske ekonto", "podnikatelsky ekonto", "podnikatelsk e konto"),
    "podnikatelsky_ucet": ("podnikatel", "podnikatelske", "business", "osvc"),
    "firemni_ucet": ("firma", "firmy", "firemni", "corporate", "pravnicke", "pravnickych"),
    "kreditni_karta": ("kreditni karta", "kreditni karty", "credit card", "kreditka"),
    "debetni_karta": ("debetni karta", "debitni karta", "debit card", "debetka"),
    "hypoteky": ("hypotek", "hypotec"),
    "pujcky": ("pujck", "uver", "spotrebitelsk"),
    "sporeni": ("sporic", "sporeni", "terminovan"),
    "investice": ("investic", "fond", "dluhopis", "akci"),
    "osobni_ucet": ("osobni", "soukrome", "soukromé", "bezny ucet"),
    "basic_payment_account": ("zakladni platebni ucet", "social account", "chraneny ucet", "chráněný účet", "vulnerable"),
}

_GENERIC_EKONTO_ALIASES: tuple[str, ...] = ("ekonto", "e konto", "e-konto", "ekonta")
_PERSONAL_EKONTO_HINTS: tuple[str, ...] = ("osobni", "soukrome", "soukromy", "pro osobni", "retail")
_BUSINESS_EKONTO_HINTS: tuple[str, ...] = ("podnikatel", "podnikatelske", "business", "osvc", "firma", "firemni")


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = _norm(phrase)
    return bool(phrase and phrase in text)


def detect_query_product(query: str) -> tuple[str | None, float, str]:
    """Map query text to a canonical product group with confidence."""
    q = _norm(query)
    has_generic_ekonto = any(_norm(alias) in q for alias in _GENERIC_EKONTO_ALIASES)
    if has_generic_ekonto:
        if any(hint in q for hint in _BUSINESS_EKONTO_HINTS):
            return "ekonto_podnikatelske", 1.0, "query_alias=ekonto+business_segment"
        if any(hint in q for hint in _PERSONAL_EKONTO_HINTS):
            return "ekonto_osobni", 1.0, "query_alias=ekonto+personal_segment"
        return "ekonto_ambiguous", 1.0, "query_alias=ekonto_without_segment"
    best: tuple[str | None, float, str] = (None, 0.0, "no_product_entity")
    for canonical, aliases in _QUERY_PRODUCT_SYNONYMS.items():
        for alias in aliases:
            alias_n = _norm(alias)
            if not alias_n:
                continue
            if alias_n in q:
                confidence = 1.0 if canonical in {"ekonto_osobni", "ekonto_podnikatelske", "podnikatelsky_ucet", "firemni_ucet"} else 0.9
                if len(alias_n.split()) == 1 and canonical not in {"investice"}:
                    confidence = min(confidence, 0.82)
                if confidence > best[1]:
                    best = (canonical, confidence, f"query_alias={alias_n}")
    # Explicit dictionary normalizations requested in the task.
    if best[0] is None:
        if "bezny ucet" in q:
            return "osobni_ucet", 0.95, "synonym=bezny_ucet->osobni_ucet"
        if "business ucet" in q:
            return "podnikatelsky_ucet", 0.95, "synonym=business_ucet->podnikatele"
        if "ucet pro firmu" in q:
            return "firemni_ucet", 0.95, "synonym=ucet_pro_firmu->firmy"
    return best


_MAINSTREAM_PRODUCT_PATTERNS = (
    r"\bekonto\b",
    r"\bekonto smart\b",
    r"\baktivní účet\b",
    r"\baktivni ucet\b",
    r"\bchytry ucet\b",
    r"\bchytry ucet\b",
)


def _is_mainstream_row(row: dict) -> bool:
    """True if row represents a currently-marketed mainstream retail product."""
    if row.get("mainstream_product") is True:
        return True
    text = _norm(_row_text(row))
    return any(re.search(p, text, flags=re.IGNORECASE) for p in _MAINSTREAM_PRODUCT_PATTERNS)


def _is_basic_payment_account_row(row: dict) -> bool:
    """True if row represents a basic payment account (Základní platební účet)."""
    text = _norm(_row_text(row))
    return any(
        _contains_phrase(text, alias)
        for alias in _ROW_PRODUCT_SYNONYMS.get("basic_payment_account", ())
    )


def _is_niche_product_row(row: dict) -> bool:
    """True if row is a niche/social/deprecated/legacy product, NOT mainstream retail."""
    if row.get("is_archived") is True or row.get("is_discontinued") is True:
        return True
    if _is_basic_payment_account_row(row):
        return True
    return False


def _is_basic_payment_account_query(query: str) -> bool:
    """True if query explicitly targets a basic payment account."""
    q = _norm(query)
    for alias in _QUERY_PRODUCT_SYNONYMS.get("basic_payment_account", ()):
        if alias in q:
            return True
    # Also check for vulnerable/social banking semantics
    if any(token in q for token in ("socialni", "chraneny", "vulnerable", "social")):
        return True
    return False


def canonical_product_for_row(row: dict) -> set[str]:
    """Infer canonical product groups from row metadata."""
    text = _norm(_row_text(row))
    groups: set[str] = set()
    for canonical, aliases in _ROW_PRODUCT_SYNONYMS.items():
        if any(_contains_phrase(text, alias) for alias in aliases):
            groups.add(canonical)
    category = _norm(str(row.get("category") or row.get("product_segment") or ""))
    has_ekonto = any(_contains_phrase(text, alias) for alias in _GENERIC_EKONTO_ALIASES)
    has_business_ekonto_hint = has_ekonto and any(hint in text for hint in _BUSINESS_EKONTO_HINTS)
    has_personal_ekonto_hint = has_ekonto and any(hint in text for hint in _PERSONAL_EKONTO_HINTS)
    if has_ekonto:
        groups.discard("ekonto_osobni")
        groups.discard("ekonto_podnikatelske")
        if has_business_ekonto_hint:
            groups.add("ekonto_podnikatelske")
            groups.add("podnikatelsky_ucet")
        elif has_personal_ekonto_hint or category == "retail":
            groups.add("ekonto_osobni")
            groups.add("osobni_ucet")
    if category == "retail" and not ({"podnikatelsky_ucet", "firemni_ucet"} & groups):
        groups.add("osobni_ucet")
    if category in {"corporate", "business"}:
        groups.add("firemni_ucet")
    return groups


def product_segment_for_row(row: dict) -> str:
    groups = canonical_product_for_row(row)
    if "ekonto_podnikatelske" in groups or "podnikatelsky_ucet" in groups:
        return "business"
    if "ekonto_osobni" in groups or "osobni_ucet" in groups:
        return "personal"
    if "firemni_ucet" in groups:
        return "corporate"
    return "unknown"


def _product_group_match(row: dict, canonical: str | None) -> bool:
    if canonical is None:
        return True
    groups = canonical_product_for_row(row)
    return canonical in groups


def _warning_doc(query: str, profile: QueryProfile, debug: dict[str, object], *, score: float = 1.0) -> Document:
    debug.setdefault("fallback_used", False)
    canonical = str(debug.get("canonical_product") or "")
    label = CANONICAL_PRODUCT_LABELS.get(canonical)
    content = NO_UNAMBIGUOUS_PRICING_MESSAGE if not label else f"Nepodařilo se najít jednoznačný aktuální ceník pro {label}."
    meta = {
        "chunk_type": "pricing_row",
        "document_type": "pricing",
        "chunk_quality": "ok",
        "structured_pricing": True,
        "product_name": "Upozornění",
        "fee_type": content,
        "fee_value": "",
        "source_url": "https://www.rb.cz",
        "source_file": "cenik rb.cz",
        "title": "Ceník Raiffeisenbank rb.cz",
        "confidence": 1.0,
        "pricing_retriever_score": score,
        "rerank_score": score,
        "hybrid_score": score,
        "query_labels": sorted(profile.labels),
        "retrieval_reasons": ["no_unambiguous_current_pricing_for_canonical_product"],
        "retrieval_debug": debug,
        # Graceful degradation signal: no real pricing data available
        "pricing_warning": True,
    }
    logger.info(f"PricingRetriever: query='{query[:60]}' → ambiguity/no-current-pricing warning")
    return Document(page_content=content, metadata=meta)


def _clarification_doc(query: str, profile: QueryProfile, debug: dict[str, object], *, score: float = 1.0) -> Document:
    debug.setdefault("fallback_used", False)
    debug["clarification_required"] = True
    debug["pricing_ranking_reason"] = "clarification_required_ambiguous_ekonto"
    meta = {
        "chunk_type": "pricing_row",
        "document_type": "pricing",
        "chunk_quality": "ok",
        "structured_pricing": True,
        "product_name": "Upřesnění",
        "fee_type": EKONTO_CLARIFICATION_MESSAGE,
        "fee_value": "",
        "confidence": 1.0,
        "pricing_retriever_score": score,
        "rerank_score": score,
        "hybrid_score": score,
        "query_labels": sorted(profile.labels),
        "retrieval_reasons": ["ambiguous_ekonto_requires_segment"],
        "retrieval_debug": debug,
    }
    logger.info(f"PricingRetriever: query='{query[:60]}' → clarification required")
    return Document(page_content=EKONTO_CLARIFICATION_MESSAGE, metadata=meta)


def _extract_year(*parts: str) -> int | None:
    years: list[int] = []
    max_reasonable_year = date.today().year + 1
    for part in parts:
        for match in re.findall(r"(?:20|19)\d{2}", str(part or "")):
            year = int(match)
            if 2000 <= year <= max_reasonable_year:
                years.append(year)
    return max(years) if years else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in (r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", r"(\d{1,2})[.](\d{1,2})[.](\d{4})"):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if len(match.group(1)) == 4:
                y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            else:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(y, m, d)
        except ValueError:
            return None
    return None


def _extract_amount(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "zdarma" in _norm(text):
        return "0"
    match = re.search(r"\d+(?:[\s.]\d{3})*(?:[,.]\d+)?", text)
    return match.group(0).replace(" ", "") if match else ""


def _normalize_pricing_metadata(row: dict) -> dict:
    """Return a copy with normalized pricing metadata used at retrieval time."""
    out = dict(row)
    source_file = str(out.get("source_file") or "")
    source_url = str(out.get("source_url") or "")
    title = str(out.get("title") or "")
    section_title = str(out.get("section_title") or "")

    document_year = out.get("document_year") or out.get("source_year")
    try:
        document_year = int(document_year) if document_year else None
    except Exception:
        document_year = None
    if document_year is None:
        document_year = _extract_year(out.get("valid_from", ""), title, section_title, source_file, source_url)

    valid_from = out.get("valid_from") or out.get("effective_date") or out.get("source_date") or ""
    valid_to = out.get("valid_to") or ""
    source_date = out.get("source_date") or valid_from or (str(document_year) if document_year else "")

    today = date.today()
    valid_from_date = _parse_date(str(valid_from))
    valid_to_date = _parse_date(str(valid_to))
    explicit_archived = _is_row_archived(out)
    valid_now = (valid_from_date is None or valid_from_date <= today) and (valid_to_date is None or valid_to_date >= today)
    # Very old ceníky are treated as archived/stale fallback unless the user explicitly asks for history.
    stale_by_year = bool(document_year and document_year <= 2020)
    is_archived = explicit_archived or stale_by_year or (valid_to_date is not None and valid_to_date < today)
    is_active = not is_archived and valid_now

    product_name = str(out.get("product_name") or "").strip()
    fee_value = str(out.get("fee_value") or out.get("amount") or "").strip()
    currency = str(out.get("currency") or "").strip()
    if not currency:
        if "kč" in fee_value.lower() or "czk" in fee_value.lower():
            currency = "CZK"
        elif "eur" in fee_value.lower() or "€" in fee_value:
            currency = "EUR"
    period = str(out.get("period") or "").strip()
    if not period and "mesic" in _norm(fee_value):
        period = "měsíčně"
    if not period and any(token in _norm(str(out.get("fee_type") or "")) for token in ("vedeni", "cena tarifu", "mesicni")):
        period = "měsíčně"

    out.update({
        "document_year": document_year,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_date": source_date,
        "is_archived": is_archived,
        "is_active": is_active,
        "product_segment": out.get("product_segment") or out.get("category") or "",
        "product_name": product_name,
        "fee_type": str(out.get("fee_type") or "").strip(),
        "amount": out.get("amount") or _extract_amount(fee_value),
        "currency": currency,
        "period": period,
        "fee_value": fee_value,
    })
    groups = canonical_product_for_row(out)
    out["canonical_product_groups"] = sorted(groups)
    out["pricing_product_segment"] = product_segment_for_row(out)
    return out


def _product_match_strength(row: dict, query: str) -> tuple[int, str]:
    q = _norm(query)
    product = _norm(str(row.get("product_name") or ""))
    if not product:
        return 0, "no_product"
    product_tokens = _tokens(product)
    q_tokens = _tokens(q)
    if ("ekonto" in product_tokens or "ekonto" in product) and ({"ekonto", "ekonta"} & q_tokens or "ekont" in q):
        return 3, "exact_product=ekonto"
    if product and product in q:
        return 3, f"exact_product={product[:40]}"
    overlap = product_tokens & q_tokens
    if overlap:
        return 2, f"product_token_overlap={','.join(sorted(overlap)[:4])}"
    return 0, "no_product_match"


def _dedupe_ranked_rows(rows: list[tuple[dict, float, list[str]]]) -> list[tuple[dict, float, list[str]]]:
    """Deduplicate identical pricing facts; keep best ranked/current row."""
    best: dict[tuple[str, str, str, str, str], tuple[dict, float, list[str]]] = {}
    for row, score, reasons in rows:
        key = (
            _norm(str(row.get("product_name") or "")),
            _norm(str(row.get("fee_type") or "")),
            _norm(str(row.get("fee_value") or row.get("amount") or "")),
            _norm(str(row.get("currency") or "")),
            _norm(str(row.get("period") or "")),
        )
        current = best.get(key)
        if current is None:
            best[key] = (row, score, reasons)
            continue
        cur_row, cur_score, _ = current
        if (row.get("document_year") or 0, score) > (cur_row.get("document_year") or 0, cur_score):
            best[key] = (row, score, reasons)
    return sorted(best.values(), key=lambda item: item[1], reverse=True)


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
    # Product shorthand: users often ask "Kolik stojí eKonto SMART?" without
    # saying "vedení účtu". For account products this should resolve to the
    # primary account/tariff fee, not secondary fees like electronic keys.
    if ("stoji" in qt or "cena" in qt) and any(token in qt for token in ("ekonto", "konto")):
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
    # Exception: credit card queries need card maintenance fee rows ("kart" stem).
    fee_type_norm = _norm(str(row.get("fee_type") or ""))
    card_pricing_query = "kredit" in q_norm
    for stem in _FEE_EXCLUDE_STEMS:
        if stem == "kart" and card_pricing_query:
            continue
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
    product_strength, product_reason = _product_match_strength(row, query)
    if product_strength:
        score += 0.9 * product_strength; reasons.append(product_reason)
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
    if row.get("is_active") is True:
        score += 0.4; reasons.append("active_row")
    if row.get("document_year"):
        score += min(0.4, max(0, int(row.get("document_year") or 0) - 2020) * 0.05)
        reasons.append(f"document_year={row.get('document_year')}")
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
    canonical_product, product_confidence, product_match_reason = detect_query_product(query)
    debug: dict[str, object] = {
        "canonical_product": canonical_product,
        "product_match_confidence": round(product_confidence, 3),
        "product_match_reason": product_match_reason,
        "matched_product_rows": 0,
        "rejected_cross_product_rows": [],
        "fallback_used": False,
    }
    if canonical_product == "ekonto_ambiguous":
        return [_clarification_doc(query, profile, debug, score=0.0)]
    if canonical_product is not None and product_confidence < PRODUCT_MATCH_CONFIDENCE_THRESHOLD:
        debug["pricing_ranking_reason"] = "blocked_low_product_match_confidence"
        return [_warning_doc(query, profile, debug, score=0.0)]

    all_scored: list[tuple[dict, float, list[str]]] = []
    malformed_rejected = 0
    malformed_reasons: list[str] = []
    rejected_cross_product: list[dict[str, object]] = []
    for row in load_pricing_rows():
        normalized = _normalize_pricing_metadata(row)
        is_valid, invalid_reason = is_valid_pricing_row(normalized)
        if not is_valid:
            malformed_rejected += 1
            if invalid_reason:
                malformed_reasons.append(invalid_reason)
            continue
        if canonical_product is not None and not _product_group_match(normalized, canonical_product):
            if len(rejected_cross_product) < 20:
                rejected_cross_product.append({
                    "product_name": normalized.get("product_name"),
                    "fee_type": normalized.get("fee_type"),
                    "fee_value": normalized.get("fee_value"),
                    "document_year": normalized.get("document_year"),
                    "row_product_groups": sorted(canonical_product_for_row(normalized)),
                    "pricing_product_segment": product_segment_for_row(normalized),
                    "source_file": normalized.get("source_file"),
                })
            continue
        if canonical_product is not None:
            debug["matched_product_rows"] = int(debug.get("matched_product_rows") or 0) + 1
        score, reasons = _score_row(normalized, query, profile)
        if score >= min_score:
            all_scored.append((normalized, score, reasons))
    debug["rejected_cross_product_rows"] = rejected_cross_product

    # --- Active / archived split --------------------------------------------
    active_scored = [(r, s, rs) for r, s, rs in all_scored if r.get("is_active") is True and not _is_row_archived(r)]
    archived_scored = [(r, s, rs) for r, s, rs in all_scored if r.get("is_active") is not True or _is_row_archived(r)]

    newest_active_year = max((int(r.get("document_year") or 0) for r, _s, _rs in active_scored), default=0)
    if newest_active_year:
        # If current active documents exist, hard-drop older active/stale-ish rows
        # from the candidate set. This prevents 2018/2020 rows from mixing with
        # 2026 rows even when they were not explicitly marked archived upstream.
        current_active = [item for item in active_scored if item[0].get("document_year") and int(item[0].get("document_year") or 0) >= newest_active_year]
        rejected_old_active = [item for item in active_scored if item not in current_active]
        if current_active:
            archived_scored.extend(rejected_old_active)
            active_scored = current_active

    debug["active_rows_count"] = len(active_scored)
    debug["archived_rows_count"] = len(archived_scored)
    debug["malformed_rejected_rows_count"] = malformed_rejected
    debug["malformed_rejected_reasons"] = sorted(set(malformed_reasons))[:10]
    debug["selected_document_year"] = newest_active_year or None
    debug["rejected_archived_rows"] = [
        {
            "product_name": r.get("product_name"),
            "fee_type": r.get("fee_type"),
            "fee_value": r.get("fee_value"),
            "document_year": r.get("document_year"),
            "source_file": r.get("source_file"),
            "canonical_product_groups": r.get("canonical_product_groups"),
            "pricing_product_segment": r.get("pricing_product_segment"),
        }
        for r, _s, _rs in archived_scored[:20]
    ]

    if canonical_product is not None and not _is_archive_query(query) and not active_scored:
        debug["pricing_ranking_reason"] = "no_active_rows_for_canonical_product"
        debug["fallback_used"] = False
        return [_warning_doc(query, profile, debug, score=0.0)]

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
        debug["pricing_ranking_reason"] = "explicit_archive_query_all_rows_allowed"
    else:
        is_primary = is_primary_account_fee_query(query)

        # Priority A: active + primary
        candidate, _ = _filter_primary(active_scored)
        if is_primary and debug.get("primary_account_fee_filter"):
            debug["active_results_count"] = len(candidate)
            debug["pricing_ranking_reason"] = "A_active_pricing_rows_exact_or_primary_product_match"
            logger.info(f"Active-primary: {len(candidate)} rows")
        # Priority B: archived + primary (only when A produced nothing)
        elif is_primary and not debug.get("primary_account_fee_filter"):
            if canonical_product is not None:
                debug["pricing_ranking_reason"] = "no_active_primary_rows_for_canonical_product"
                debug["fallback_used"] = False
                return [_warning_doc(query, profile, debug, score=0.0)]
            candidate, _ = _filter_primary(archived_scored)
            if debug.get("primary_account_fee_filter"):
                debug["archived_fallback_used"] = "true"
                debug["fallback_used"] = True
                debug["pricing_ranking_reason"] = "D_archived_pricing_rows_fallback_no_active_primary"
                debug["primary_rows"] = len(candidate)
                logger.info(f"Archived-primary fallback: {len(candidate)} rows")
            else:
                # Priority C: active general (no primary at all)
                candidate = active_scored or archived_scored
                debug["fallback_used"] = bool(not active_scored and archived_scored)
                debug["active_results_count"] = len(candidate)
                debug["pricing_ranking_reason"] = "C_active_general_fallback_no_primary"
                logger.info(f"General fallback (no primary): {len(candidate)} rows")
        else:
            # Non-primary query: active first, archived fallback
            candidate = active_scored or archived_scored
            if not active_scored and archived_scored:
                debug["archived_fallback_used"] = "true"
                debug["fallback_used"] = True
                debug["pricing_ranking_reason"] = "D_archived_pricing_rows_fallback_no_active"
            else:
                debug["pricing_ranking_reason"] = "B_active_pricing_rows_semantic_match"
            debug["active_results_count"] = len(candidate)
            logger.info(
                f"{'Active' if active_scored else 'Archived'}-first: {len(candidate)} rows"
            )

    # --- Rank & build docs ---------------------------------------------------
    def _rank_key(item: tuple[dict, float, list[str]]) -> tuple[int, int, int, float]:
        row, score, _reasons = item
        product_strength, _ = _product_match_strength(row, query)
        return (
            1 if row.get("is_active") is True else 0,
            int(row.get("document_year") or 0),
            product_strength,
            score,
        )

    ranked_all = sorted(candidate, key=_rank_key, reverse=True)
    ranked = _dedupe_ranked_rows(ranked_all)[:top_k]
    q_norm = _norm(query)
    ranked_text = " ".join(_norm(_row_text(r)) for r, _s, _rs in ranked)
    if canonical_product == "hypoteky" and any(term in q_norm for term in ("odhad", "oceneni", "nemovit")) and not any(term in ranked_text for term in ("odhad", "oceneni", "nemovit")):
        debug["pricing_ranking_reason"] = "blocked_cross_fee_type_for_mortgage_valuation"
        debug["fallback_used"] = False
        return [_warning_doc(query, profile, debug, score=0.0)]
    if canonical_product == "apple_google_pay" and any(term in q_norm for term in ("apple pay", "google pay", "pay")) and not any(term in ranked_text for term in ("apple pay", "google pay", "pay")):
        debug["pricing_ranking_reason"] = "blocked_cross_product_for_wallet_pricing"
        debug["fallback_used"] = False
        return [_warning_doc(query, profile, debug, score=0.0)]
    debug["selected_pricing_rows"] = [
        {
            "product_name": r.get("product_name"),
            "fee_type": r.get("fee_type"),
            "fee_value": r.get("fee_value"),
            "amount": r.get("amount"),
            "currency": r.get("currency"),
            "period": r.get("period"),
            "document_year": r.get("document_year"),
            "is_active": r.get("is_active"),
            "is_archived": r.get("is_archived"),
            "source_file": r.get("source_file"),
            "canonical_product_groups": r.get("canonical_product_groups"),
            "pricing_product_segment": r.get("pricing_product_segment"),
        }
        for r, _s, _rs in ranked
    ]
    docs: list[Document] = []
    for row, score, reasons in ranked:
        content = (
            f"Produkt: {row.get('product_name', '')}\n"
            f"{row.get('fee_type', 'Poplatek')}: {row.get('fee_value', '')}\n"
            f"Částka: {row.get('amount', '')}\n"
            f"Měna: {row.get('currency', '')}\n"
            f"Období: {row.get('period', '')}\n"
            f"Platnost od: {row.get('valid_from', '')}\n"
            f"Platnost do: {row.get('valid_to', '')}\n"
            f"Rok dokumentu: {row.get('document_year', '')}\n"
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

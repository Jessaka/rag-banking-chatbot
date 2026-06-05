"""
RAG chain pro generování odpovědí na bankovní dotazy.

Podporuje čtyři LLM backendy (config.LLM_BACKEND):
  - "ollama"     → lokální Mistral/Llama přes Ollama (bez cloudu)
  - "anthropic"  → claude-haiku-4-5 přes Anthropic SDK s prompt cachingem
  - "gemini"     → gemini-2.0-flash přes Google Gemini SDK (google-genai)
  - "openai"     → gpt-4.1-mini (fallback gpt-4o-mini) s retry a rate-limit handling

Pipeline: retriever → format_context → LLM → odpověď
Konverzační mód: query rewriting + paměť posledních N zpráv
"""

from __future__ import annotations

import time
import re
from collections.abc import Generator
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

import config
from src.generation.prompts import format_context, get_conversational_prompt, get_query_rewrite_prompt, get_simple_prompt
from src.generation.product_intelligence import (
    generate_overview_fallback,
    get_product,
    find_product_by_canonical_label,
    PRODUCT_REGISTRY,
)
from src.generation.confidence_semantics import (
    ConfidenceSemantics,
    resolve_confidence_semantics,
)
from src.generation.pricing_response_formatter import format_conditional_fee, format_tiered_pricing
from src.retrieval.query_classifier import classify_query
from src.utils.logger import get_logger

logger = get_logger(__name__)

NO_ANSWER_MARKERS = (
    "nenalezl jsem",
    "nenašel jsem",
)

AMBIGUITY_PATTERNS = (
    (re.compile(r"jak[yý]\s+účet\s+je\s+pro\s+mě\s+nejlepší", re.I), "account_advisory"),
    (re.compile(r"kolik\s+stoj[ií]\s+účet\??$", re.I), "generic_account_pricing"),
    (re.compile(r"chci\s+kartu.*kolik\s+stoj", re.I), "generic_card_pricing"),
    (re.compile(r"mohu\s+investici\s+kdykoliv\s+prodat", re.I), "investment_liquidity"),
)

IDENTITY_PATTERNS = (
    re.compile(r"^\s*kdo\s+(jste|jsi)\s*\??\s*$", re.I),
    re.compile(r"^\s*co\s+(jste|jsi)\s+(zač|zac)\s*\??\s*$", re.I),
    re.compile(r"^\s*co\s+umíte\s*\??\s*$", re.I),
    re.compile(r"^\s*s\s+čím\s+pomůžete\s*\??\s*$", re.I),
    re.compile(r"^\s*s\s+cim\s+pomuzete\s*\??\s*$", re.I),
    re.compile(r"^\s*jsi\s+(banka|rb|raiffeisenbank)\s*\??\s*$", re.I),
    re.compile(r"^\s*kdo\s+je\s+(rb|raiffeisenbank)\s*\??\s*$", re.I),
)

IDENTITY_RESPONSE = (
    "Jsem AI asistent Raiffeisenbank a pomohu vám s informacemi o účtech, "
    "kartách, platbách, hypotékách, investicích a dalších službách RB. "
    "Nejsem banka ani pracovník pobočky; odpovídám podle dostupných informací "
    "Raiffeisenbank a u citlivých nebo závazných úkonů doporučím ověření přímo u RB."
)

UNSUPPORTED_RESPONSE = (
    "Nepodařilo se najít dostatečně spolehlivou odpověď v dostupných zdrojích RB. "
    "Abych si nevymýšlel, doporučuji ověřit dotaz přímo v internetovém bankovnictví, "
    "na pobočce nebo na zákaznické lince Raiffeisenbank."
)

RESILIENCE_RESPONSES = {
    "supported_but_missing_data": (
        "Dotaz spadá do oblasti služeb Raiffeisenbank, ale v dostupných aktuálních zdrojích "
        "jsem nenašel dostatečně konkrétní podklad. Abych si nevymýšlel, doporučuji ověřit "
        "detail v internetovém bankovnictví, na pobočce nebo na zákaznické lince RB."
    ),
    "unsupported_domain": (
        "Tento dotaz nespadá do oblasti informací, které mohu bezpečně zodpovědět z dostupných "
        "zdrojů Raiffeisenbank. Mohu pomoct s účty, kartami, platbami, hypotékami, investicemi "
        "a běžnými postupy RB."
    ),
    "governance_suppressed": (
        "Našel jsem pouze zdroje, které bezpečnostní pravidla vyhodnotila jako nevhodné pro odpověď "
        "(například archivní nebo nahrazené dokumenty). Abych nepoužil zastaralý údaj, doporučuji "
        "ověření přímo u Raiffeisenbank."
    ),
    "retrieval_timeout": (
        "Vyhledávání ve zdrojích tentokrát vypršelo. Zkuste dotaz zopakovat nebo ho zúžit; u závazných "
        "informací doporučuji ověření přímo v kanálech Raiffeisenbank."
    ),
    "low_confidence_retrieval": (
        "Našel jsem jen slabě související zdroje a nechci z nich odvozovat nepřesnou odpověď. "
        "Zkuste prosím dotaz upřesnit názvem produktu nebo typu služby."
    ),
}

EKONTO_CLARIFICATION = (
    "Upřesněte prosím, zda myslíte osobní eKonto, nebo podnikatelské eKonto. "
    "Stačí odpovědět například „osobní“ nebo „podnikatelské“."
)

GUIDED_FLOW_PATTERNS = (
    (re.compile(r"(ztratil|ztratila|ztrata|ztráta|ukrad|odcizen).*(kart\w*)|blokac[ei]\w*\s+kart\w*|zablok\w+.*kart\w*|kart\w+.*zablok\w*", re.I), "card_blocking"),
    (re.compile(r"(co\s+m[aá]m\s+d[eě]lat|neoprávněn|neopravnen|podezřel).*(platb|transakc|karta)", re.I), "complaint"),
    (re.compile(r"(jak\s+zadat|údaje|udaje|iban|bic).*(sepa|swift|zahraničn|zahranicn)", re.I), "sepa_swift"),
    (re.compile(r"(rb\s+klíč|rb\s+klic).*(aktiv|nefung|odblok|přen|pren|telefon|mobil)", re.I), "rb_key"),
    (re.compile(r"(jak\s+požádat|jak\s+pozadat|chci|vyřídit|vyridit).*(hypot[eé]k)", re.I), "mortgage"),
    (re.compile(r"bankomat\w*|pobočk\w*|pobocek|kde.*(bankomat|pobočk|pobock)|najít.*(bankomat|pobočk)|hledat.*(bankomat|pobočk)", re.I), "branch_atm"),
    (re.compile(r"(jak\s+)?(zru[šs]it|zru[šs]en[íi]|uzav[řr][íi]t|uzav[řr]en[íi]|cancel|close).*(ú[čc]et|ucet|account)", re.I), "account_closure"),
)

# --- Priority 3: Procedural flow patterns ---
# These run before retrieval (like guided flows) for deterministic how-to answers.
PROCEDURAL_FLOW_PATTERNS = (
    (re.compile(r"(jak\s+)?(aktiv[uo]j|aktivovat|zapnout|zapni|zač[íi]t\s+pou[žz][íi]v[aá]t).*(kart\w*|plateb)", re.I), "activation_flow"),
    (re.compile(r"(jak\s+)?(zv[ýy][šs][íi][mtš]|zv[ýy][šs]it|nav[ýy][šs][íi][mtš]|nav[ýy][šs]it|sn[íi][žz][íi][mtš]|sn[íi][žz]it).*(limit|kart|v[ýy]b[eě]r)", re.I), "card_limit_flow"),
    (re.compile(r"(jak\s+)?(zm[eě]n[íi]t|zm[eě]n[aá]|nastav[íi]t|nastavit).*(limit).*(kart\w*)?|(jak\s+)?limit.*(zm[eě]n[íi]t|nastavit)", re.I), "card_limit_flow"),
    (re.compile(r"(jak\s+)?(p[řr]idat|nahr[aá]t|m[íi]t).*(kart).*(mobil|apple|google|watch|hodink)", re.I), "mobile_wallet_flow"),
    (re.compile(r"(karta|kartou|kartu|pou[žz]it[íi]).*(zahrani[čc][íi]|cizina|usa|eu|sv[ěe]t)", re.I), "abroad_card_usage"),
    (re.compile(r"(karta|kartou|kartu|funguje).*(v\s+)?zahrani[čc]", re.I), "abroad_card_usage"),
    (re.compile(r"(m[aá]te|nab[íi]z[íi]te).*(visa|mastercard).*|(visa|mastercard).*(nebo|or|vs|versus)", re.I), "card_brand_overview"),
    # Additional patterns for short/noisy queries
    (re.compile(r"karta\s+v\s+mobilu", re.I), "mobile_wallet_flow"),
    (re.compile(r"kart[au]\s+v\s+mobilu", re.I), "mobile_wallet_flow"),
)

# --- Priority 2: Soft guidance patterns ---
# For common FAQ/procedural queries where retrieval is weak but the
# domain is supported and the risk is low.
SOFT_GUIDANCE_FAQ_PATTERNS = (
    (re.compile(r"raia|asistentka\s+raia|co\s+(je|umí|umi|dělá|dela)\s+raia", re.I), "raia_info"),
    (re.compile(r"(co\s+(je|to\s+je)|jak\s+funguje).*(apple\s*pay|google\s*pay|plac[eě]n[íi]\s+mobilem|plac[eě]n[íi]\s+hodinkami)", re.I), "apple_google_pay"),
    (re.compile(r"(jak\s+)?funguje\s+(plateb|kart|limit|v[ýy]b[eě]r|mobil)", re.I), "card_how_it_works"),
    (re.compile(r"(co\s+)?je\s+(to\s+)?(kredit|debet|limit|disponibil|z[ůu]statek)", re.I), "card_what_is"),
    (re.compile(r"(jak\s+)?(m[ůu][žz]u|mohu|lze|jde)\s+(pou[žz][íi]t|platit|v[ýy]brat)", re.I), "card_usage_can_i"),
    (re.compile(r"(pot[řr]ebuju|potrebuju|chci|mus[íi]m).*(kart|platit|limit)", re.I), "card_need_help"),
    (re.compile(r"poji[sš]t[eě]n[íi].*(vozidel|auto)|poji[sš]ten[ií].*(vozidel|auto)|povinné?\s+ru[čc]en|povinné?\s+ruceni|havarijní|havarijni\s+poji", re.I), "vehicle_insurance"),
    # Konkrétní produkty — investice (PŘED catalog, aby matchovaly dříve)
    (re.compile(r"raiffeisen\s*(dynamick|konzervativn|balancovan|progresivn|fond)|dynamick\w*[\s\w]*fond|popis[\s\w]*fond|fond[\s\w]*popis", re.I), "investice_fondy_detail"),
    (re.compile(r"\bdip\b|dlouhodob[\s\w]*investičn|investičn[\s\w]*produkt[\s\w]*dlouhodob|jak[\s\w]*funguje[\s\w]*dip", re.I), "investice_dip"),
    (re.compile(r"asset[\s.]*management|spr[aá]v[aá][\s\w]*portfolia|portfolio[\s.]*management|slu[žz]by[\s\w]*náro[čc]n|wealth[\s.]*management|privátní[\s\w]*bankovnictv|private[\s.]*banking", re.I), "investice_sluzby_narocne"),
    (re.compile(r"pravidelné?\s*investic|investov[\s\w]*pravidelné?", re.I), "investice_pravidelne"),
    (re.compile(r"podílov[éý][\s\w]*fond|fond[\s\w]*invest", re.I), "investice_fondy"),
    # Catalog overview patterns (obecné dotazy na celé kategorie)
    (re.compile(r"druh\w*.{0,10}spo[rř]|jak[eé]\w*.{0,10}spo[rř]|spo[rř][íi]c[íi].{0,10}produkt|typ\w*.{0,10}spo[rř]", re.I), "catalog_sporeni"),
    (re.compile(r"jak[eé]\w*.{0,10}invest|druh\w*.{0,10}invest|investičn\w*.{0,10}produkt|co.*invest\w+", re.I), "catalog_investice"),
    (re.compile(r"jak[eé]\w*.{0,10}poji[sš]t|druh\w*.{0,10}poji[sš]t|typ\w*.{0,10}poji[sš]t|nab[íi]z[íi]\w*.{0,10}poji[sš]t", re.I), "catalog_pojisteni"),
    (re.compile(r"jak[eé]\w*.{0,10}hypot|druh\w*.{0,10}hypot|typ\w*.{0,10}hypot|nab[íi]z[íi]\w*.{0,10}hypot", re.I), "catalog_hypoteky"),
    (re.compile(r"jak[eé]\w*.{0,10}p[ůu]j[čc]k|druh\w*.{0,10}p[ůu]j[čc]|typ\w*.{0,10}p[ůu]j[čc]|nab[íi]z[íi]\w*.{0,10}p[ůu]j[čc]", re.I), "catalog_pujcky"),
    # Konkrétní produkty — hypotéky
    (re.compile(r"odpov[eě]dn[aá][\s\w]*hypot|hypot[\s\w]*ekologick", re.I), "hypoteka_odpovedna"),
    (re.compile(r"americk[aá][\s\w]*hypot|hypot[\s\w]*(cokoliv|na\s+cokoliv)", re.I), "hypoteka_americka"),
    (re.compile(r"hypot[\s\w]*pron[aá]jem|pron[aá]jem[\s\w]*hypot", re.I), "hypoteka_pronajem"),
    (re.compile(r"rekop[ůu]j[čc]k|p[ůu]j[čc]k[\s\w]*rekonstrukc|rekonstrukc[\s\w]*p[ůu]j[čc]k", re.I), "hypoteka_rekopujcka"),
    (re.compile(r"refinancov[\s\w]*hypot|hypot[\s\w]*refinancov", re.I), "hypoteka_refinancovani"),
    # Konkrétní produkty — spoření
    (re.compile(r"termínovan[ýéaý][\s\w]*vklad|vklad[\s\w]*termínovan", re.I), "sporeni_terminovany_vklad"),
    (re.compile(r"stavební[\s\w]*spořen|spořen[\s\w]*stavební|stavební[\s\w]*sporitel", re.I), "sporeni_stavebni"),
    (re.compile(r"bonusov[ýéaý][\s\w]*spořic|spořic[\s\w]*bonusov|bonusov[ýéaý][\s\w]*účet", re.I), "sporeni_bonusovy"),
    # Konkrétní produkty — pojištění
    (re.compile(r"osobní[\s\w]*strážce|osobni[\s\w]*strazce|strážce[\s\w]*poji|strazce[\s\w]*pojist|poji[sš]t[\s\w]*strážce|pojisten[\s\w]*strazce", re.I), "pojisteni_osobni_strazce"),
    (re.compile(r"pojist[\s\w]*naplno|naplno[\s\w]*pojist|cestovní[\s\w]*naplno", re.I), "pojisteni_naplno"),
    (re.compile(r"úrazové?\s*pojist|pojist[\s\w]*úrazov|\bopora\b", re.I), "pojisteni_urazove"),
    (re.compile(r"životní[\s\w]*pojist|pojist[\s\w]*život", re.I), "pojisteni_zivotni"),
    (re.compile(r"majetkov[éé][\s\w]*pojist|pojist[\s\w]*majetek|pojist[\s\w]*majetkov", re.I), "pojisteni_majetkove"),
    # Konkrétní produkty — účty
    (re.compile(r"chytr[ýéaý][\s\w]*účet|bezn[ýéaý][\s\w]*účet[\s\w]*zdarma|účet[\s\w]*zdarma[\s\w]*bez\s*podmínek", re.I), "ucet_chytry"),
    (re.compile(r"dětský[\s\w]*účet|účet[\s\w]*dět|účet[\s\w]*dítě", re.I), "ucet_detsky"),
    (re.compile(r"studentský[\s\w]*účet|účet[\s\w]*student", re.I), "ucet_studentsky"),
)


def _identity_intent(question: str) -> bool:
    return any(pattern.search(question or "") for pattern in IDENTITY_PATTERNS)


def _identity_debug(retrieval_query: str) -> list[dict]:
    return [{
        "retrieval_route": "identity",
        "retrieval_skipped": True,
        "system_identity_route": True,
        "faq_priority_used": False,
        "metadata_boost_reason": [],
        "rewritten_query": retrieval_query,
        "authority_boost_used": False,
        "stale_penalty_used": False,
    }]


def _ux_meta(
    bucket: str,
    reason: str,
    *,
    clarification_required: bool = False,
    unsupported_reason: str | None = None,
    confidence_factors: dict | None = None,
) -> dict:
    """Build UX metadata including confidence factors (Priority 4).

    confidence_factors can include:
      - authority_boost_used: bool  — document authority scoring applied
      - stale_penalty_used: bool    — stale/archived docs penalized
      - soft_guidance_used: bool    — soft guidance mode active
      - retrieval_weak: bool        — no or low-confidence sources
      - fallback_used: bool         — any fallback was triggered
      - pricing_grounding: bool     — exact pricing row matched
      - source_count: int           — number of unique sources
    """
    return {
        "confidence_bucket": bucket,
        "confidence_reason": reason,
        "clarification_required": clarification_required,
        "unsupported_reason": unsupported_reason,
        "confidence_factors": confidence_factors or {},
    }


def _debug_with_ux(rows: list[dict], ux: dict) -> list[dict]:
    if not rows:
        return [ux]
    return [{**row, **ux} for row in rows]


def _empty_retrieval_resilience(profile, forced_category: str | None = None) -> tuple[str, str, dict]:
    """Return (category, answer, ux_meta) for explicit empty retrieval semantics."""
    supported = "supported_domain" in profile.labels or any(
        label in profile.labels
        for label in (
            "pricing", "cards", "accounts", "payments", "mortgages", "investments",
            "support", "product_overview", "account_overview", "card_overview",
            "insurance", "stavebni_sporeni", "payment_services",
            "digital_banking", "rb_club", "support_general",
        )
    )
    category = forced_category or ("supported_but_missing_data" if supported else "unsupported_domain")
    answer = RESILIENCE_RESPONSES[category]
    ux = _ux_meta(
        "low",
        f"empty retrieval resilience: {category}",
        unsupported_reason=category,
        confidence_factors={
            "retrieval_weak": True,
            "fallback_used": True,
            "source_count": 0,
            "resilience_category": category,
            "escalation_strategy": "ask_support_or_branch" if supported else "redirect_to_supported_scope",
        },
    )
    return category, answer, ux


def _is_ekonto_ambiguous_pricing(question: str) -> bool:
    q = (question or "").lower()
    return "ekonto" in q and any(k in q for k in ("kolik", "stoj", "poplatek", "vedení", "vedeni")) and not any(
        k in q for k in ("osobní", "osobni", "smart", "komplet", "podnikat", "firem", "firma", "osvč", "osvc")
    )


def _resolve_pending_clarification(question: str, context: dict | None) -> tuple[str, str, str] | None:
    """Resolve a follow-up answer to a pending clarification.

    Handles multiple clarification types beyond eKonto segment:
    - ekonto_pricing → osobní/podnikatelské/firemní/student/premium/smart/komplet
    - generic_account → personal/business/corporate/student
    """
    if not context:
        return None
    ctype = context.get("type")
    q = (question or "").lower().strip()

    if ctype == "ekonto_pricing":
        target, product_label = _clarification_answer_interpreter(q, "ekonto")
        if target:
            query_text = _clarification_query(product_label, "ekonto")
            return query_text, product_label, "pricing"
        return None

    if ctype == "generic_account":
        target, product_label = _clarification_answer_interpreter(q, "account")
        if target:
            query_text = _clarification_query(product_label, "account")
            return query_text, product_label, "pricing"
        return None

    return None


def _clarification_query(product_label: str, context_type: str) -> str:
    """Build a grammatically correct rewritten query from product label and context."""
    label = product_label.lower()
    if context_type == "ekonto":
        if "osobní" in label:
            return "Kolik stojí vedení osobního eKonta?"
        if "podnikatelské" in label:
            return "Kolik stojí vedení podnikatelského eKonta?"
        if "smart" in label:
            return "Kolik stojí vedení eKonto SMART?"
        if "komplet" in label:
            return "Kolik stojí vedení eKonto KOMPLET?"
        if "výhody" in label or "prémium" in label:
            return "Kolik stojí vedení eKonto Výhody Prémium?"
        if "student" in label:
            return "Kolik stojí vedení eKonto STUDENT?"
        return f"Kolik stojí vedení {product_label}?"
    if context_type == "account":
        if "osobní" in label:
            return "Jaký je poplatek za vedení osobního účtu?"
        if "podnikatelský" in label:
            return "Jaký je poplatek za vedení podnikatelského účtu?"
        if "studentský" in label:
            return "Jaký je poplatek za vedení studentského účtu?"
        return f"Jaký je poplatek za vedení {product_label}?"
    return f"Kolik stojí {product_label}?"


def _clarification_answer_interpreter(answer: str, context_type: str) -> tuple[str | None, str]:
    """Interpret a user's clarification answer and return (target_canonical, product_label).

    Context types:
      - "ekonto": resolve eKonto variant
      - "account": resolve generic account type

    Returns (None, original_answer) if no match found.
    """
    a = answer.strip().lower()

    # --- eKonto variants ---
    if context_type == "ekonto":
        if any(k in a for k in ("osob", "soukrom", "retail")):
            return "ekonto_osobni", "osobní eKonto"
        if any(k in a for k in ("podnik", "osvč", "osvc", "firma", "firem")):
            return "ekonto_podnikatelske", "podnikatelské eKonto"
        if "smart" in a or "chytry" in a:
            return "ekonto_osobni", "eKonto SMART"
        if "komplet" in a:
            return "ekonto_osobni", "eKonto KOMPLET"
        if "premium" in a or "vyhody" in a:
            return "ekonto_osobni", "eKonto Výhody Prémium"
        if "student" in a:
            return "ekonto_osobni", "eKonto STUDENT"
        return None, a

    # --- Generic account types ---
    if context_type == "account":
        if any(k in a for k in ("osob", "soukrom", "retail")):
            return "osobni_ucet", "osobní účet"
        if any(k in a for k in ("podnik", "osvč", "osvc", "firma", "firem")):
            return "podnikatelsky_ucet", "podnikatelský účet"
        if "student" in a:
            return "osobni_ucet", "studentský účet"
        return None, a

    return None, a


def _guided_flow_intent(question: str) -> str | None:
    for pattern, intent in GUIDED_FLOW_PATTERNS:
        if pattern.search(question or ""):
            return intent
    return None


def _unsupported_intent(question: str) -> str | None:
    q = (question or "").lower()
    if any(k in q for k in ("krypto", "bitcoin", "ethereum", "nft")):
        return "unsupported_crypto"
    return None


def _comparison_intent(question: str) -> bool:
    """Detect whether the question has a comparison intent."""
    if not question:
        return False
    q = question.lower()
    from src.generation.comparison_engine import COMPARISON_KEYWORDS
    return any(kw in q for kw in COMPARISON_KEYWORDS) and len(q) > 15


def _guided_flow_answer(intent: str) -> str:
    flows = {
        "card_blocking": (
            "Doporučený postup při ztrátě nebo podezření na zneužití karty:\n"
            "1. Kartu ihned zablokujte v mobilním/internetovém bankovnictví, pokud ho máte k dispozici.\n"
            "2. Pokud se do bankovnictví nedostanete, zavolejte na nonstop linku blokace karet:\n"
            "   📞 412 446 402 (nonstop 24/7)\n"
            "3. Zkontrolujte poslední transakce a podezřelé platby reklamujte.\n"
            "4. Nikomu nesdělujte PIN, hesla ani autorizační kódy.\n\n"
            "Jde o bezpečnostní situaci — jednejte co nejrychleji."
        ),
        "complaint": (
            "Reklamaci platby nebo karetní transakce doporučuji řešit takto:\n"
            "1. Připravte údaje o platbě/transakci a dostupné doklady.\n"
            "2. Podejte reklamaci v bankovnictví, na pobočce nebo přes podporu RB.\n"
            "3. U neoprávněné karetní transakce zároveň zvažte blokaci karty.\n"
            "4. Sledujte stav reklamace a reagujte na případné doplnění podkladů."
        ),
        "sepa_swift": (
            "Pro zahraniční platbu rozlišujte SEPA a SWIFT podle typu platby:\n"
            "- SEPA se typicky používá pro EUR platby v rámci SEPA prostoru.\n"
            "- SWIFT se používá pro jiné zahraniční/mezibankovní platby.\n"
            "Připravte si zejména IBAN příjemce, případně BIC/SWIFT, částku, měnu a údaje příjemce."
        ),
        "rb_key": (
            "U RB klíče postupujte podle situace:\n"
            "1. Při aktivaci nebo přenosu do nového telefonu použijte mobilní aplikaci / bankovnictví RB.\n"
            "2. Pokud RB klíč nefunguje, zkontrolujte internet, aktuální verzi aplikace a čas v telefonu.\n"
            "3. Při podezření na zneužití kontaktujte podporu RB a nepotvrzujte neznámé požadavky."
        ),
        "mortgage": (
            "U hypotéky obvykle pomůže postupovat v těchto krocích:\n"
            "1. Upřesnit účel hypotéky a orientační cenu nemovitosti.\n"
            "2. Připravit údaje o příjmech, výdajích a vlastních zdrojích.\n"
            "3. Porovnat fixaci, sazbu, poplatky a možnost mimořádných splátek.\n"
            "4. Domluvit si další postup s hypotečním specialistou RB."
        ),
        "branch_atm": (
            "Pro vyhledání bankomatů a poboček Raiffeisenbank použijte oficiální vyhledávač:\n"
            "🏧 https://www.rb.cz/o-nas/kontakty/pobocky-a-bankomaty\n\n"
            "Vyhledávač umožňuje filtrovat podle města, otevírací doby a dostupných služeb."
        ),
        "account_closure": (
            "Postup pro zrušení účtu u Raiffeisenbank:\n\n"
            "1. Vyrovnejte zůstatek — převeďte prostředky na jiný účet.\n"
            "2. Zrušte vázané produkty:\n"
            "   - Trvalé platební příkazy a inkasa\n"
            "   - Debetní karty a povolené přečerpání (kontokorent)\n"
            "   - Souhlasy s inkasem (SIPO, pojistné)\n"
            "3. Podejte žádost o zrušení:\n"
            "   - Osobně na pobočce Raiffeisenbank\n"
            "   - Telefonicky: 800 900 900 (zdarma, nonstop)\n"
            "   - Prostřednictvím internetového bankovnictví (u vybraných typů účtů)\n"
            "4. Banka zpracuje žádost — lhůta zpravidla do 30 dnů.\n\n"
            "Upozornění: Archivujte výpisy, oznamte nové číslo účtu plátcům.\n"
            "Zrušení s nesplaceným záporným zůstatkem nebo exekucí není možné."
        ),
    }
    return flows[intent]


# --- Priority 3: Procedural flow answer formatters ---

PROCEDURAL_FLOW_ANSWERS: dict[str, str] = {
    "activation_flow": (
        "Aktivace karty obvykle probíhá takto:\n"
        "1. Novou kartu aktivujte v internetovém nebo mobilním bankovnictví RB.\n"
        "2. Postupujte podle pokynů v aplikaci — obvykle stačí potvrdit aktivaci.\n"
        "3. Po aktivaci je karta ihned připravena k použití.\n"
        "4. U bezkontaktních karet lze platit bez zadání PINu do částky 500 Kč.\n\n"
        "Pokud máte s aktivací potíže, kontaktujte zákaznickou podporu RB."
    ),
    "card_limit_flow": (
        "Změnu limitu karty můžete řešit takto:\n"
        "1. V internetovém nebo mobilním bankovnictví zkontrolujte aktuální limit.\n"
        "2. Pokud potřebujete limit navýšit, zažádejte o změnu v bankovnictví.\n"
        "3. U bezhotovostních plateb a výběrů z bankomatu platí zpravidla oddělené limity.\n"
        "4. Pro konkrétní limity a podmínky doporučuji zkontrolovat smluvní dokumentaci.\n\n"
        "Konkrétní výše limitu závisí na typu karty a bonitě klienta."
    ),
    "mobile_wallet_flow": (
        "Použití karty v mobilu je možné přes Apple Pay (iPhone) nebo Google Pay (Android):\n"
        "1. Přidejte svou platební kartu do aplikace Peněženka (Wallet) v telefonu.\n"
        "2. Postupujte podle pokynů — obvykle stačí naskenovat kartu nebo zadat údaje.\n"
        "3. Aktivaci potvrďte kódem z SMS nebo v bankovní aplikaci.\n"
        "4. Poté můžete platit mobilem na všech bezkontaktních terminálech.\n\n"
        "Apple Pay a Google Pay jsou v ČR široce akceptovány."
    ),
    "abroad_card_usage": (
        "Použití karty v zahraničí:\n"
        "1. Kartu Raiffeisenbank lze použít ve většině zemí světa.\n"
        "2. Platby v cizí měně jsou přepočteny kurzem banky s případným poplatkem.\n"
        "3. Výběry z bankomatů v zahraničí mohou být zpoplatněny podle ceníku.\n"
        "4. Pro platby v eurech v SEPA prostoru jsou poplatky obvykle nižší.\n\n"
        "Doporučuji před cestou zkontrolovat aktuální poplatky v ceníku RB."
    ),
    "card_brand_overview": (
        "Raiffeisenbank vydává platební karty ve spolupráci se společnostmi "
        "Mastercard a Visa. Konkrétní značka závisí na typu karty:\n"
        "- Debetní karty k běžnému účtu mohou být Mastercard nebo Visa.\n"
        "- Kreditní karty jsou často Mastercard.\n"
        "- Virtuální karty a mobilní platby využívají stejnou značku.\n\n"
        "Obě značky jsou celosvětově akceptovány — Mastercard i Visa fungují "
        "v ČR i v zahraničí."
    ),
}


def _procedural_flow_intent(question: str) -> str | None:
    for pattern, intent in PROCEDURAL_FLOW_PATTERNS:
        if pattern.search(question or ""):
            return intent
    return None


def _procedural_flow_answer(intent: str) -> str:
    if intent in PROCEDURAL_FLOW_ANSWERS:
        return PROCEDURAL_FLOW_ANSWERS[intent]
    return UNSUPPORTED_RESPONSE


# --- Priority 2: Soft guidance formatters ---

SOFT_GUIDANCE_ANSWERS: dict[str, str] = {
    # Hypotéky — konkrétní produkty
    "hypoteka_odpovedna": (
        "Odpovědná hypotéka je ekologická hypotéka Raiffeisenbank pro energeticky úsporné nemovitosti.\n\n"
        "Výhoda: zvýhodněná úroková sazba při energeticky úsporné nemovitosti (energetický štítek A nebo B).\n"
        "Vhodné pro: novostavby, rekonstrukce na nízkoenergetický standard.\n\n"
        "Více informací: https://www.rb.cz/osobni/hypoteky/nabidka-hypotek/odpovedna-hypoteka"
    ),
    "hypoteka_americka": (
        "Hypotéka na cokoliv (americká hypotéka) umožňuje čerpat peníze na libovolný účel se zástavou nemovitosti.\n\n"
        "Výhody: volné použití peněz (auto, dovolená, investice...), nižší sazba než u spotřebitelského úvěru.\n"
        "Podmínka: vlastnictví nemovitosti vhodné jako zástava.\n\n"
        "Více informací: https://www.rb.cz/osobni/hypoteky/nabidka-hypotek/americka-hypoteka"
    ),
    "hypoteka_pronajem": (
        "Hypotéka na pronájem je určena pro koupi nemovitosti k pronájmu.\n\n"
        "Vhodné pro: investory kupující byt nebo dům za účelem pronájmu.\n"
        "Příjem z pronájmu lze zahrnout do bonity při posuzování žádosti.\n\n"
        "Více informací: https://www.rb.cz/osobni/hypoteky/nabidka-hypotek/hypoteka-na-pronajem"
    ),
    "hypoteka_rekopujcka": (
        "RekoPůjčka je půjčka na rekonstrukci BEZ zástavy nemovitosti.\n\n"
        "Výše: až 2 500 000 Kč\n"
        "Výhoda: nepotřebujete zástavní právo — rychlejší sjednání, bez ocenění nemovitosti.\n"
        "Vhodné pro: rekonstrukce, modernizace, vybavení.\n\n"
        "Více informací: https://www.rb.cz/osobni/hypoteky/nabidka-hypotek/rekopujcka"
    ),
    "hypoteka_refinancovani": (
        "Refinancování hypotéky umožňuje převést hypotéku od jiné banky k Raiffeisenbank za výhodnějších podmínek.\n\n"
        "Výhody: nižší úroková sazba, lepší podmínky, možnost navýšení úvěru.\n"
        "Doporučená doba: ke konci fixačního období u stávající banky.\n\n"
        "Více informací: https://www.rb.cz/osobni/hypoteky/sluzby-k-hypotekam/refinancovani-hypoteky"
    ),
    # Investice — konkrétní produkty
    "investice_pravidelne": (
        "Pravidelné investice umožňují investovat od malých částek každý měsíc do podílových fondů.\n\n"
        "Výhody: průměrování nákladů (dollar-cost averaging), začít lze i s malou částkou.\n"
        "Sjednání: přes aplikaci Raiffeisen Investice nebo na pobočce.\n\n"
        "Více informací: https://www.rb.cz/osobni/zhodnoceni-uspor/investice/pravidelne-investice"
    ),
    "investice_fondy": (
        "Podílové fondy Raiffeisenbank nabízí různé investiční strategie:\n\n"
        "- Konzervativní: nízké riziko, dluhopisy a peněžní trh\n"
        "- Vyvážené: kombinace akcií a dluhopisů\n"
        "- Dynamické: vyšší podíl akcií, vyšší potenciální výnos i riziko\n\n"
        "Více informací: https://www.rb.cz/osobni/zhodnoceni-uspor/investice/podilove-fondy"
    ),
    "investice_fondy_detail": (
        "Raiffeisenbank nabízí tyto podílové fondy:\n\n"
        "**Raiffeisen Konzervativní**\n"
        "- Pro investory zaměřené na uchování hodnoty\n"
        "- Nízké riziko, dluhopisy a peněžní trh\n\n"
        "**Raiffeisen Balancovaný**\n"
        "- Kombinace akcií a dluhopisů, střední riziko\n\n"
        "**Raiffeisen Progresivní**\n"
        "- Vyšší podíl akcií, zaměřený na výnos a růst\n\n"
        "**Raiffeisen Dynamický**\n"
        "- Alespoň 85 % v akciích, sleduje MSCI AC World Index\n"
        "- Minimální horizont: 5 let, pro investory s nízkou averzí k riziku\n\n"
        "Více: https://www.rb.cz/osobni/zhodnoceni-uspor/investice/podilove-fondy"
    ),
    "investice_dip": (
        "Dlouhodobý investiční produkt (DIP) je státem podporovaný způsob spoření na důchod.\n\n"
        "Výhody DIP:\n"
        "- Daňová úleva: odečtete až 48 000 Kč ročně ze základu daně\n"
        "- Příspěvek zaměstnavatele: osvobozen od daně a odvodů\n"
        "- Flexibilita: výběr fondů dle rizikového profilu\n"
        "- Dlouhodobé zhodnocení: investice do podílových fondů\n\n"
        "Podmínky:\n"
        "- Minimální délka spoření: 10 let\n"
        "- Výplata nejdříve v 60 letech věku\n"
        "- Při nedodržení podmínek: vrácení daňových výhod\n\n"
        "Více: https://www.rb.cz/osobni/zhodnoceni-uspor/investice/dip"
    ),
    "investice_sluzby_narocne": (
        "Raiffeisenbank nabízí individuální investiční služby pro náročné klienty:\n\n"
        "Služby pro náročné:\n"
        "- Osobní investiční poradce\n"
        "- Individuální správa portfolia (asset management)\n"
        "- Přístup k zahraničním trhům a cenným papírům\n"
        "- Analýzy a investiční doporučení\n\n"
        "Privátní bankovnictví:\n"
        "- Komplexní finanční plánování\n"
        "- Prémiové podmínky produktů\n"
        "- Dedikovaný vztahový manažer\n\n"
        "Více: https://www.rb.cz/osobni/zhodnoceni-uspor/investice/sluzby-pro-narocne"
    ),
    # Spoření — konkrétní produkty
    "sporeni_terminovany_vklad": (
        "Termínovaný vklad nabízí pevnou úrokovou sazbu na dobu určitou.\n\n"
        "Výhody: garantovaný výnos, bez rizika poklesu sazby.\n"
        "Omezení: peníze jsou uloženy na pevnou dobu (nelze vybrat předčasně bez sankce).\n"
        "Vhodné pro: konzervativní spoření s definovaným horizontem.\n\n"
        "Více informací: https://www.rb.cz/osobni/zhodnoceni-uspor/sporeni/terminovany-vklad"
    ),
    "sporeni_stavebni": (
        "Stavební spoření Raiffeisenbank (Raiffeisen stavební spořitelna):\n\n"
        "- Garantovaná úroková sazba: 3,3 % p.a.\n"
        "- Státní podpora: až 2 000 Kč ročně\n"
        "- Zhodnocení vkladů: až 4,2 % p.a. po dobu šesti let\n"
        "- Možnost stavebního úvěru po 6 letech spoření\n"
        "- Sjednání: online nebo na pobočce, zdarma\n\n"
        "Více informací: https://www.rb.cz/osobni/zhodnoceni-uspor/sporeni/stavebni-sporeni"
    ),
    "sporeni_bonusovy": (
        "Bonusový spořicí účet Raiffeisenbank:\n\n"
        "- Úroková sazba: až 4,2 % p.a.\n"
        "- Vedení účtu: zdarma\n"
        "- Likvidní: peníze jsou kdykoli dostupné\n"
        "- Automatické spoření: nastavte si převody z běžného účtu\n\n"
        "Více informací: https://www.rb.cz/osobni/ucty/sporici-ucty/bonusovy-ucet"
    ),
    # Pojištění — konkrétní produkty
    "pojisteni_osobni_strazce": (
        "Pojištění Osobní strážce — 89 Kč měsíčně\n\n"
        "Pro klienty s běžným účtem nebo kreditní kartou RB.\n\n"
        "Kryje:\n"
        "- Neoprávněné transakce: zneužití ztracené/odcizené karty (s PIN i bez), zneužití karty v mobilní peněžence, zneužití mobilního/internetového bankovnictví\n"
        "- Ztráta nebo odcizení: platební karty, doklady, klíče od bytu/domu/auta, peněženka, příruční zavazadlo\n"
        "- Odcizení: mobilní telefon, notebook, tablet, brýle\n"
        "- Kybernetická asistence: právní pomoc (neoprávněná transakce, poškození pověsti, zneužití osobních údajů), IT asistence (napadení počítače/mobilu), pojištění nákupu online (nedodání nebo poškozené zboží)\n\n"
        "Nekryje:\n"
        "- Věci, které nejsou v pojištění zahrnuty\n"
        "- Věci pojištěné pouze na odcizení (ne ztrátu)\n"
        "- Hrubou nedbalost (poskytnutí PIN, hesel, kliknutí na podvodný odkaz)\n\n"
        "Více: https://www.rb.cz/osobni/pojisteni/pojisteni-k-produktum/osobni-strazce"
    ),
    "pojisteni_naplno": (
        "Cestovní pojištění NAPLNO — pro držitele debetní karty Raiffeisenbank:\n\n"
        "Limity pojistného krytí:\n"
        "- Léčebné výlohy: až 8 000 000 Kč\n"
        "- Pojištění odpovědnosti: až 5 000 000 Kč\n"
        "- Storno poplatky: až 30 000 Kč\n\n"
        "Výhody:\n"
        "- Chrání i členy rodiny (i bez držitele karty)\n"
        "- Cesta až 120 dní\n"
        "- Kryje zimní sporty a turistiku do 3 500 m n.m.\n"
        "- Asistenční linka Europ Assistance: +420 246 059 444 (24/7)\n\n"
        "Více informací: https://www.rb.cz/osobni/pojisteni/cestovni-pojisteni/cestovni-pojisteni-naplno"
    ),
    "pojisteni_urazove": (
        "Úrazové pojištění OPORA kryje úrazy a jejich následky.\n\n"
        "Krytí zahrnuje: denní odškodné při pracovní neschopnosti, trvalé následky, smrt úrazem.\n"
        "Sjednání: na pobočce Raiffeisenbank nebo přes zákaznickou linku 800 900 900.\n\n"
        "Více informací: https://www.rb.cz/osobni/pojisteni/dalsi-pojisteni/urazove-pojisteni"
    ),
    "pojisteni_zivotni": (
        "Životní pojištění Raiffeisenbank nabízí ochranu pro případ smrti a připojištění.\n\n"
        "Zahrnuje: pojištění pro případ smrti, invalidity, vážných nemocí.\n"
        "Poskytovatel: UNIQA pojišťovna ve spolupráci s Raiffeisenbank.\n"
        "Sjednání: na pobočce s poradcem.\n\n"
        "Více informací: https://www.rb.cz/osobni/pojisteni/dalsi-pojisteni/zivotni-pojisteni"
    ),
    "pojisteni_majetkove": (
        "Majetkové pojištění Raiffeisenbank chrání váš majetek a odpovědnost.\n\n"
        "Kryje: požár, záplavu, vichřici, krádež, vandalismus, odpovědnost za škodu.\n"
        "Poskytovatel: UNIQA pojišťovna ve spolupráci s Raiffeisenbank.\n"
        "Sjednání: online nebo na pobočce.\n\n"
        "Více informací: https://www.rb.cz/osobni/pojisteni/dalsi-pojisteni/majetkove-pojisteni"
    ),
    # Účty — konkrétní produkty
    "ucet_chytry": (
        "CHYTRÝ účet Raiffeisenbank je bezpodmínečně zdarma:\n\n"
        "- Vedení účtu: 0 Kč (zdarma napořád, bez podmínek)\n"
        "- Výběry z bankomatů v ČR a v zahraničí: 0 Kč\n"
        "- Příchozí i odchozí platby: 0 Kč\n"
        "- Okamžité platby 24/7: zdarma\n\n"
        "Akce pro nové klienty:\n"
        "- Odměna 6× 500 Kč (při 10 platbách kartou měsíčně po 6 měsíců)\n\n"
        "Více informací: https://www.rb.cz/osobni/ucty/bezne-ucty/chytry-ucet"
    ),
    "ucet_detsky": (
        "Dětský účet Raiffeisenbank je určen pro klienty mladší 18 let.\n\n"
        "Výhody: vedení zdarma, debetní karta, spoření pro děti.\n"
        "Správa: zákonný zástupce spravuje účet, dítě může mít přístup.\n\n"
        "Více informací: https://www.rb.cz/osobni/ucty/bezne-ucty/student/detsky-ucet"
    ),
    "ucet_studentsky": (
        "Studentský účet Raiffeisenbank pro studenty 18+.\n\n"
        "Výhody: vedení zdarma, výhodné podmínky pro studenty.\n"
        "Podmínka: prokázání studia na střední nebo vysoké škole.\n\n"
        "Více informací: https://www.rb.cz/osobni/ucty/bezne-ucty/student/studentsky-ucet"
    ),
    "catalog_sporeni": (
        "Raiffeisenbank nabízí tyto spořicí produkty:\n\n"
        "- **Bonusový spořicí účet**: až 4,2 % p.a., bez poplatků\n"
        "  → rb.cz/osobni/ucty/sporici-ucty/bonusovy-ucet\n"
        "- **Termínovaný vklad**: pevná sazba na dobu určitou\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/sporeni/terminovany-vklad\n"
        "- **Stavební spoření**: 3,3 % p.a. garantovaně, státní podpora až 2 000 Kč/rok\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/sporeni/stavebni-sporeni\n"
        "- **Drobné spoření**: zaokrouhlení plateb na spořicí účet\n"
        "- **Pravidelné spoření**: automatické měsíční převody zdarma"
    ),
    "catalog_investice": (
        "Raiffeisenbank nabízí tyto investiční produkty:\n\n"
        "- **Pravidelné investice**: od malých částek každý měsíc\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/investice/pravidelne-investice\n"
        "- **Podílové fondy**: konzervativní, vyvážené i dynamické\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/investice/podilove-fondy\n"
        "- **DIP (Dlouhodobý investiční produkt)**: daňová úleva až 48 000 Kč/rok\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/investice/dip\n"
        "- **Mobilní aplikace Raiffeisen Investice**: správa portfolia v mobilu\n"
        "- **Služby pro náročné**: individuální investiční poradenství\n"
        "  → rb.cz/osobni/zhodnoceni-uspor/investice/sluzby-pro-narocne"
    ),
    "catalog_pojisteni": (
        "Raiffeisenbank nabízí tato pojištění:\n\n"
        "**Pojištění k produktům:**\n"
        "- Pojištění ke kreditním kartám (Osobní strážce)\n"
        "- Pojištění schopnosti splácet hypotéku\n"
        "- Pojištění schopnosti splácet půjčku\n\n"
        "**Cestovní pojištění:**\n"
        "- Cestovní pojištění NAPLNO: léčebné výlohy až 8 000 000 Kč\n\n"
        "**Ostatní pojištění:**\n"
        "- Úrazové pojištění OPORA\n"
        "- Životní pojištění\n"
        "- Majetkové pojištění\n"
        "- Pojištění vozidel (ve spolupráci s UNIQA)\n\n"
        "Více informací: rb.cz/osobni/pojisteni"
    ),
    "catalog_hypoteky": (
        "Raiffeisenbank nabízí tyto hypoteční produkty:\n\n"
        "- **Hypotéka na bydlení**: koupi nemovitosti nebo výstavbu\n"
        "- **Odpovědná hypotéka**: zvýhodněná pro ekologické bydlení\n"
        "- **Hypotéka na cokoliv (americká)**: bez určení účelu\n"
        "- **Hypotéka na pronájem**: financování investiční nemovitosti\n"
        "- **RekoPůjčka (bez zástavy)**: rekonstrukce bez zástavního práva\n"
        "- **Refinancování hypotéky**: převod z jiné banky za výhodnějších podmínek\n\n"
        "Hypoteční kalkulačka: rb.cz/osobni/hypoteky/hypotecni-kalkulacka\n"
        "Více informací: rb.cz/osobni/hypoteky"
    ),
    "catalog_pujcky": (
        "Raiffeisenbank nabízí tyto půjčky a úvěry:\n\n"
        "- **Minutová půjčka**: až 1 200 000 Kč, od 4,9 % p.a., online, 0 Kč poplatků\n"
        "- **Kontokorent (přečerpání účtu)**: flexibilní rezerva na běžném účtu\n"
        "- **Půjčka na auto**: online sjednání bez poplatků za vedení\n"
        "- **Půjčka na rekonstrukci**: bez zástavy nemovitostí\n"
        "- **Sloučení půjček (RePůjčka)**: nižší splátky, vše pod jednou střechou\n"
        "- **PlatímPak**: odložená platba — nakoupíte nyní, zaplatíte později\n\n"
        "Kalkulačka: rb.cz/osobni/pujcky"
    ),
    "vehicle_insurance": (
        "Pojištění vozidel nabízí Raiffeisenbank ve spolupráci s pojišťovnou UNIQA.\n\n"
        "Dostupné produkty:\n"
        "- Povinné ručení (POV) — zákonná povinnost každého provozovatele vozidla\n"
        "- Havarijní pojištění — kryje škody na vlastním vozidle\n\n"
        "Sjednání:\n"
        "- Online nebo na pobočce Raiffeisenbank\n"
        "- Zákaznická linka: 800 900 900\n\n"
        "Více informací: https://www.rb.cz/osobni/pojisteni/pojisteni-vozidel"
    ),
    "apple_google_pay": (
        "Apple Pay a Google Pay jsou služby pro bezkontaktní platby mobilem nebo hodinkami.\n\n"
        "Apple Pay (iPhone / Apple Watch):\n"
        "- Otevřete Peněženku (Wallet) → přidejte kartu RB\n"
        "- Aktivaci potvrďte SMS kódem nebo v aplikaci RB\n"
        "- Plaťte přiložením telefonu k terminálu\n\n"
        "Google Pay (Android):\n"
        "- Otevřete aplikaci Google Wallet → přidejte kartu RB\n"
        "- Aktivaci potvrďte SMS nebo přes aplikaci RB\n"
        "- Plaťte přiložením telefonu k terminálu\n\n"
        "Oba systémy fungují na všech terminálech s bezkontaktní platbou (NFC).\n"
        "Karta je chráněna — číslo karty se nesdílí s obchodníkem.\n\n"
        "Více informací: rb.cz/osobni/karty/placeni-mobilem"
    ),
    "raia_info": (
        "RAIA je AI asistentka Raiffeisenbank dostupná v mobilní aplikaci a na webu.\n\n"
        "Co RAIA umí:\n"
        "- Odpovídat na otázky o produktech a službách RB\n"
        "- Pomoct s orientací v bankovnictví\n"
        "- Zjednodušovat bankovní služby pomocí umělé inteligence\n\n"
        "Co RAIA neumí:\n"
        "- Zobrazovat osobní údaje nebo zustatky (napr. 'za co jste mi strhli 19 Kc')\n"
        "- Zpracovat více dotazů najednou nebo příliš dlouhé otázky\n\n"
        "Více informací: https://www.rb.cz/informacni-servis/asistentka-raia"
    ),
    "card_how_it_works": (
        "Platební karta funguje tak, že umožňuje bezhotovostní platby "
        "a výběry z bankomatu. Každá karta je navázána na váš účet "
        "(debetní karta čerpá z disponibilního zůstatku, kreditní karta "
        "čerpá z úvěrového limitu). Karta je chráněna PIN kódem, "
        "u bezkontaktních plateb do 500 Kč PIN nepotřebujete.\n\n"
        "Pro podrobnější informace o poplatcích a limitech doporučuji "
        "zkontrolovat ceník RB nebo detail vašeho produktu."
    ),
    "card_what_is": (
        "Základní pojmy u platebních karet:\n"
        "- Debetní karta: karta napojená na běžný účet, platíte jen "
        "z vlastních peněz na účtu.\n"
        "- Kreditní karta: karta s úvěrovým limitem, peníze půjčuje "
        "banka a vy je splácíte.\n"
        "- Limit karty: maximální částka, kterou můžete kartou zaplatit "
        "nebo vybrat v určitém období.\n"
        "- Disponibilní zůstatek: volné prostředky na účtu k dispozici.\n\n"
        "Konkrétní parametry se liší podle typu produktu."
    ),
    "card_usage_can_i": (
        "Ano, kartu Raiffeisenbank můžete běžně používat k platbám "
        "v obchodech, online, v zahraničí i k výběrům z bankomatu. "
        "Limity se liší podle typu karty a nastavení v bankovnictví.\n\n"
        "Pro konkrétní dotaz doporučuji zkontrolovat podmínky vašeho "
        "produktu nebo kontaktovat podporu RB."
    ),
    "card_need_help": (
        "Rád vám pomůžu. Pokud jde o platební kartu, můžete zjistit "
        "informace o limitech, poplatcích, použití v zahraničí nebo "
        "aktivaci v internetovém bankovnictví RB.\n\n"
        "Upřesněte prosím, s čím konkrétně potřebujete poradit – "
        "např. aktivace karty, limit, mobilní platby nebo blokace."
    ),
}


def _soft_guidance_intent(question: str) -> str | None:
    for pattern, intent in SOFT_GUIDANCE_FAQ_PATTERNS:
        if pattern.search(question or ""):
            return intent
    return None


def _soft_guidance_answer(intent: str) -> str | None:
    if intent in SOFT_GUIDANCE_ANSWERS:
        return SOFT_GUIDANCE_ANSWERS[intent]
    return None


def _ambiguity_intent(question: str) -> str | None:
    for pattern, intent in AMBIGUITY_PATTERNS:
        if pattern.search(question):
            return intent
    return None


def _clarification_answer(intent: str) -> str:
    if intent == "account_advisory":
        return (
            "Upřesněte prosím potřeby, abych mohl doporučit vhodný účet:\n"
            "- jde o osobní účet, podnikání nebo firmu?\n"
            "- chcete hlavně nízké poplatky, kartu, výběry, zahraniční platby nebo spoření?\n"
            "- budete účet používat aktivně každý měsíc?"
        )
    if intent == "generic_account_pricing":
        return "Upřesněte prosím, jestli myslíte osobní běžný účet, podnikatelský účet, firemní účet nebo konkrétní eKonto."
    if intent == "generic_card_pricing":
        return "Upřesněte prosím, kterou karta myslíte: debetní kartu, kreditní kartu, nebo kartu k podnikatelskému/firemnímu účtu."
    if intent == "investment_liquidity":
        return (
            "Záleží na konkrétním investičním produktu. Upřesněte prosím, jestli jde o fond, DIP, dluhopis, akcie nebo jiný produkt. "
            "U investic se mohou lišit lhůty pro vypořádání, poplatky i rizika."
        )
    return "Upřesněte prosím, který konkrétní produkt nebo situaci máte na mysli."


def _normalize_answer_text(answer: str, *, answer_strategy: str) -> str:
    text = str(answer or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if answer_strategy in {"generic_llm", "pricing_section_llm", "pricing_table_llm"} and "Zdroj" not in text:
        text = f"{text}\n\nZdroj: viz uvedené zdroje níže."
    return text


def _extract_fee_value_from_text(text: str) -> str:
    patterns = (
        r"\bzdarma\b",
        r"\b\d+[\s\d]*(?:[,.]\d+)?\s*(?:Kč|CZK)(?:\s*(?:měsíčně|mesicne|ročně|rocne|za\s+\w+))?",
        r"\b\d+[,.]?\d*\s*%",
        r"\b\d+[\s\d]*(?:[,.]\d+)?\s*(?:měsíčně|mesicne|ročně|rocne)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def extract_structured_pricing_answer(doc: Document) -> dict | None:
    """Extract a deterministic answer from an atomic pricing_row chunk."""
    md = doc.metadata
    if md.get("chunk_type") != "pricing_row":
        return None
    if str(md.get("chunk_quality") or "ok").lower() == "bad_table_row":
        return None

    product_name = str(md.get("product_name") or "").strip()
    fee_type = str(md.get("fee_type") or "").strip()
    fee_value = str(md.get("fee_value") or "").strip() or _extract_fee_value_from_text(doc.page_content)
    if not product_name or not (fee_type or fee_value):
        return None

    source_url = str(md.get("source_url") or md.get("url") or "").strip()
    file_name = str(md.get("file_name") or md.get("source_file") or Path(source_url).name or md.get("title") or "zdroj").strip()
    page = md.get("page")
    return {
        "product_name": product_name,
        "fee_type": fee_type or "Poplatek",
        "fee_value": fee_value,
        "period": str(md.get("period") or "").strip(),
        "conditional_pricing_detected": md.get("conditional_pricing_detected") is True,
        "base_price": md.get("base_price"),
        "conditional_price": md.get("conditional_price"),
        "condition_type": md.get("condition_type"),
        "condition_text": md.get("condition_text"),
        "pricing_logic": md.get("pricing_logic"),
        "tiers": md.get("tiers") or [],
        "currency": md.get("currency") or md.get("normalized_currency") or "CZK",
        "billing_period": md.get("normalized_billing_period"),
        "source_url": source_url,
        "source_label": file_name,
        "title": str(md.get("title") or "Ceník Raiffeisenbank").strip(),
        "page": page,
    }


def _pricing_row_confidence_high(doc: Document) -> bool:
    if doc.metadata.get("chunk_type") != "pricing_row":
        return False
    if str(doc.metadata.get("chunk_quality") or "ok").lower() == "bad_table_row":
        return False
    if doc.metadata.get("structured_pricing"):
        try:
            if float(doc.metadata.get("confidence", 0.0)) < 0.70:
                return False
        except Exception:
            return False
    if not extract_structured_pricing_answer(doc):
        return False
    score = doc.metadata.get("rerank_score")
    try:
        return score is None or float(score) >= max(0.0, config.RERANK_MIN_SCORE)
    except Exception:
        return True


def _format_structured_pricing_answer(data: dict) -> str:
    page = f", str. {data['page']}" if data.get("page") else ""
    fee_line = f"{data['fee_type']}: {data['fee_value']}" if data.get("fee_value") else data["fee_type"]
    return (
        f"Produkt: {data['product_name']}\n"
        f"{fee_line}\n"
        f"Zdroj: {data['source_label']}{page}"
        + (f"\nURL: {data['source_url']}" if data.get("source_url") else "")
    )


# ---------------------------------------------------------------------------
# Graceful degradation helpers (P1 — Pricing → Overview fallback)
# ---------------------------------------------------------------------------


def _has_real_pricing_docs(source_docs: list[Document], structured_docs: list[Document]) -> bool:
    """Check if there are real (non-warning) pricing documents available."""
    for doc in structured_docs:
        if not doc.metadata.get("pricing_warning", False):
            return True
    for doc in source_docs:
        if doc.metadata.get("document_type") == "pricing" and not doc.metadata.get("pricing_warning", False):
            return True
    return False


def _detect_product_for_degradation(
    source_docs: list[Document],
    query_profile: object,
    session_debug: dict,
) -> str | None:
    """Detect the most likely product ID for overview fallback.

    Resolution order:
      1. Session context (resolved_product from previous turn)
      2. Query profile labels → product domain map
      3. Source doc product_name (non-warning)
      4. Canonical product label from pricing retrieval metadata
      5. Debug info from session
    """
    # 1. Session context (most reliable)
    resolved = session_debug.get("resolved_product") or session_debug.get("inherited_product")
    if resolved and get_product(resolved):
        return resolved

    # 2. Query labels → product domain map
    label_product_map = {
        "osobni_ucty": "ekonto_osobni",
        "kreditni_karty": "kreditni_karta",
        "hypoteky": "hypoteky",
        "investice": "investice",
        "rb_klic": "rb_klic",
        "sepa_swift": "sepa_swift",
        "apple_google_pay": "apple_google_pay",
        "cards": "debetni_karta",
        "pujcky": "pujcky",
        "sporeni": "sporeni",
    }
    labels = getattr(query_profile, "labels", set()) or set()
    for label in labels:
        pid = label_product_map.get(label)
        if pid and get_product(pid):
            return pid

    # 3. Source doc product_name (skip warning docs)
    for doc in source_docs:
        pname = doc.metadata.get("product_name", "")
        if pname and pname not in ("Upozornění", "Upřesnění", ""):
            # Try direct product match
            if pname in PRODUCT_REGISTRY:
                return pname
            # Try canonical label match
            product = find_product_by_canonical_label(pname)
            if product:
                return product.product_id

    # 4. Canonical from pricing debug metadata
    for doc in source_docs:
        debug = doc.metadata.get("retrieval_debug", {}) or {}
        canonical = debug.get("canonical_product", "")
        if canonical:
            product = find_product_by_canonical_label(canonical)
            if product:
                return product.product_id

    return None


def _build_overview_fallback_response(
    product_id: str,
    question: str,
    source_docs: list[Document],
    retrieval_query: str,
    retrieval_ms: float,
    t_ask: float,
) -> dict:
    """Build a graceful degradation response with overview fallback instead of dead-end warning."""
    overview = generate_overview_fallback(product_id, question)
    cs = resolve_confidence_semantics(
        "overview_fallback",
        reason=f"Přesměrováno z ceníku na popis produktu {product_id}",
    )

    total_ms = (time.perf_counter() - t_ask) * 1000
    logger.info(
        f"Answer strategy: overview_fallback (graceful degradation from pricing; "
        f"product={product_id})"
    )

    return {
        "answer": overview,
        "sources": source_docs,
        "rewritten_query": retrieval_query,
        "answer_strategy": "overview_fallback",
        "answer_confidence": cs.bucket,
        "confidence_origin": cs.origin,
        "degraded_answer": cs.degraded,
        "confidence_semantic_label": cs.semantic_label,
        "confidence_origin_label": cs.origin_label,
        "retrieval_debug": None,
        **ux_meta_from_semantics(cs, clarification_required=False, unsupported_reason=None),
        "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
    }


def ux_meta_from_semantics(
    cs: ConfidenceSemantics,
    clarification_required: bool = False,
    unsupported_reason: str | None = None,
) -> dict:
    """Build the _ux_meta style dict from ConfidenceSemantics."""
    return {
        "confidence_bucket": cs.bucket,
        "confidence_reason": cs.reason,
        "confidence_origin": cs.origin,
        "confidence_origin_label": cs.origin_label,
        "confidence_semantic_label": cs.semantic_label,
        "degraded_answer": cs.degraded,
        "clarification_required": clarification_required,
        "unsupported_reason": unsupported_reason,
        "confidence_factors": {
            "confidence_origin": cs.origin,
            "degraded_answer": cs.degraded,
        },
    }


def _enrich_return_with_semantics(return_dict: dict) -> dict:
    """Add confidence semantics fields to any return dict that lacks them.

    Handles both _ux_meta style (confidence_bucket) and enriched style.
    Safe to call on any return — no-ops if fields already present.
    """
    if "confidence_origin" in return_dict:
        return return_dict  # Already enriched

    strategy = return_dict.get("answer_strategy", "generic_llm")
    bucket = return_dict.get("confidence_bucket")
    reason = return_dict.get("confidence_reason", "")
    cs = resolve_confidence_semantics(strategy, bucket=bucket, reason=reason)

    return_dict["confidence_origin"] = cs.origin
    return_dict["confidence_origin_label"] = cs.origin_label
    return_dict["confidence_semantic_label"] = cs.semantic_label
    return_dict["degraded_answer"] = cs.degraded
    return return_dict


def _enrich_dead_end_answer(answer_text: str, product_id: str | None = None) -> str:
    """If an answer is a dead-end (unsupported/warning only), append an actionable
    recommendation instead of leaving the user with a dead-end state."""
    dead_end_markers = [
        "nepodařilo se najít jednoznačný",
        "nenalezl jsem",
        "nenašel jsem",
        "kontaktujte zákaznickou linku",
        "nedokážu odpovědět",
        "nemám dostatek informací",
    ]
    if not any(marker in answer_text.lower() for marker in dead_end_markers):
        return answer_text

    if product_id:
        product = get_product(product_id)
        if product:
            return f"{answer_text}\n\n{product.cta_text}"

    return (
        f"{answer_text}\n\n"
        f"Doporučujeme ověřit informaci v internetovém bankovnictví, "
        f"na pobočce nebo na zákaznické lince Raiffeisenbank."
    )


def _structured_pricing_docs(source_docs: list[Document]) -> list[Document]:
    return [
        doc for doc in source_docs
        if doc.metadata.get("structured_pricing") is True and _pricing_row_confidence_high(doc)
    ]


def normalize_product_name(name: str) -> str:
    """Lightweight suffix cleanup for pricing product names.

    Strips known trailing suffixes (e.g. "cena", "vedení účtu") while
    preserving specific product names that include those words as part of
    their official name.
    """
    if not name:
        return name
    raw = name.strip()

    # Preserve specific product names exactly (case-insensitive)
    preserve_lower = frozenset({
        "ekonto smart",
        "ekonto výhody prémium",
        "ekonto vyhody premium",
        "aktivní účet",
        "aktivni ucet",
        "ekonto komplet",
    })
    if raw.lower() in preserve_lower:
        return raw

    # Ordered by length (longest first) — strip at most one suffix.
    # NOTE: "cena" is listed separately (not "základní cena") so that
    # "eKonto Základní cena" → "eKonto Základní" rather than "eKonto".
    suffixes = [
        "vedení jednoho běžného účtu měsíčně",
        "vedení jednoho běžného účtu",
        "vedení účtu měsíčně",
        "vedení účtu",
        "měsíčně",
        "v ceně",
        "cena",
    ]
    for suffix in suffixes:
        if raw.lower().endswith(suffix.lower()):
            stripped = raw[:-len(suffix)].strip()
            return stripped if stripped else raw
    return raw


def _clean_fee_label(label: str) -> str:
    label = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", label or "").strip()
    label = re.sub(r"\s+\d+\)\s*$", "", label).strip()
    if not label:
        return "poplatek"
    return label[:1].lower() + label[1:]


def _format_value_with_period(value: str, period: str) -> str:
    if not period:
        return value
    if period.lower() in value.lower():
        return value
    return f"{value} {period}"


def _source_display_name(data: dict) -> str:
    title = str(data.get("title") or "").strip()
    source_label = str(data.get("source_label") or "").strip()
    if title and title.lower() not in {"nový ceník", "novy cenik", "zde"}:
        return title
    if source_label:
        return "Ceník Raiffeisenbank"
    return "Ceník Raiffeisenbank"


def _minimal_structured_sources(docs: list[Document]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    sources: list[dict] = []
    for doc in docs:
        data = extract_structured_pricing_answer(doc)
        if not data:
            continue
        key = (data.get("source_label", ""), str(data.get("page") or ""), data.get("source_url", ""))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "title": _source_display_name(data),
            "page": data.get("page"),
            "url": data.get("source_url"),
        })
    return sources[:3]


def _credit_card_products_from_docs(docs: list[Document]) -> list[str]:
    """Return the full RB payment card catalog for catalog-intent queries."""
    return [
        "Debetní karta (k běžnému účtu)",
        "Kreditní karta EASY",
        "Kreditní karta STYLE",
        "Kreditní karta RB PREMIUM",
        "Kreditní karta Visa Gold",
        "Kreditní karta O2 RB",
    ]


def _format_credit_card_catalog_answer(docs: list[Document]) -> str | None:
    products = _credit_card_products_from_docs(docs)
    if not products:
        return None
    lines = ["Raiffeisenbank nabízí tyto platební karty:", ""]
    for product in products:
        if "debetní" in product.lower():
            desc = "karta napojená na běžný účet; vydává se automaticky k eKontu (Mastercard nebo Visa)."
        elif "easy" in product.lower():
            desc = "základní kreditní karta zdarma."
        elif "style" in product.lower():
            desc = "kreditní karta s cashback odměnami."
        elif "premium" in product.lower():
            desc = "prémiová kreditní karta (199 Kč/měs)."
        elif "visa gold" in product.lower():
            desc = "kreditní karta Visa Gold s cestovními výhodami."
        elif "o2" in product.lower():
            desc = "partnerská kreditní karta O2 RB Club."
        else:
            desc = "platební karta Raiffeisenbank."
        lines.append(f"- {product}: {desc}")
    lines.extend([
        "",
        "Pro porovnání podmínek, limitů a poplatků doporučuji detail produktu na rb.cz.",
    ])
    first = docs[0]
    source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    lines.append(f"\nZdroj: {source}")
    return "\n".join(lines)


def _format_card_overview_answer(docs: list[Document]) -> str | None:
    if not docs:
        return None
    hay = "\n".join(
        " ".join([
            str(doc.metadata.get("title") or doc.metadata.get("file_name") or ""),
            str(doc.metadata.get("source_url") or doc.metadata.get("url") or ""),
            doc.page_content[:4000],
        ])
        for doc in docs
    ).lower()
    card_signal = any(term in hay for term in ("platební karta", "platebni karta", "debetní", "debetni", "kreditní", "kreditni", "mastercard", "visa", "karty"))
    if not card_signal:
        return None
    first = docs[0]
    source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    return (
        "Raiffeisenbank u platebních karet obvykle rozlišuje tyto typy:\n"
        "- Debetní karty: karty navázané na běžný účet pro běžné platby a výběry.\n"
        "- Kreditní karty: úvěrové karty s čerpáním do sjednaného limitu.\n"
        "- Digitální/virtuální použití karty: podle dostupnosti lze kartu používat i pro online nebo mobilní platby.\n"
        "- Kartové varianty Mastercard/Visa: konkrétní značka a parametry závisí na produktu.\n\n"
        "Pro konkrétní kartu je dobré porovnat poplatky, limity, bonusy a podmínky v detailu produktu.\n\n"
        f"Zdroj: {source}"
    )


def _format_account_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for account overview queries."""
    if docs:
        hay = "\n".join(
            " ".join([
                str(doc.metadata.get("title") or doc.metadata.get("file_name") or ""),
                str(doc.metadata.get("source_url") or doc.metadata.get("url") or ""),
                doc.page_content[:4000],
            ])
            for doc in docs
        ).lower()
        account_signal = any(term in hay for term in (
            "běžný účet", "bezny ucet", "osobní účet", "osobni ucet", "ekonto",
            "aktivní účet", "aktivni ucet", "podnikatelský", "podnikatelsky", "firemní", "firemni"
        ))
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        account_signal = False
        source = "rb.cz"

    return (
        "Raiffeisenbank v dostupných zdrojích uvádí tyto typy účtů:\n"
        "- Osobní běžné účty (např. eKonto, Aktivní účet)\n"
        "- Podnikatelské účty (např. eKonto podnikatelské)\n"
        "- Firemní účty\n\n"
        "Pro srovnání poplatků, podmínek a výhod konkrétního účtu doporučuji "
        "otevřít detail produktu nebo ceník.\n\n"
        f"Zdroj: {source}"
    )


def _format_mortgage_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for mortgage overview queries."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    return (
        "Raiffeisenbank v dostupných zdrojích nabízí hypoteční úvěry na bydlení "
        "včetně možnosti refinancování. Hypoteční produkty se liší účelem, "
        "fixací úrokové sazby, výší poplatků a možnostmi mimořádných splátek.\n\n"
        "Pro výběr vhodné hypotéky doporučuji porovnat sazby, RPSN a podmínky "
        "v detailu produktu.\n\n"
        f"Zdroj: {source}"
    )


def _format_investment_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for investment overview queries."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    return (
        "Raiffeisenbank v dostupných zdrojích uvádí investiční produkty jako "
        "podílové fondy, dluhopisy, DIP (dlouhodobý investiční produkt) a další "
        "cenné papíry. Investice se liší rizikovostí, výnosovým potenciálem "
        "a dobou trvání.\n\n"
        "Pro konkrétní nabídku a informace o rizicích doporučuji otevřít detail "
        "produktu nebo konzultaci s investičním specialistou RB.\n\n"
        f"Zdroj: {source}"
    )


def _format_rb_key_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for RB klíč overview queries."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    return (
        "RB klíč je bezpečnostní prvek pro přihlašování a autorizaci plateb "
        "v mobilním a internetovém bankovnictví Raiffeisenbank. Slouží "
        "k potvrzování transakcí, přihlášení do aplikace a ověřování operací.\n\n"
        "Pro aktivaci nebo obnovu RB klíče doporučuji postupovat podle pokynů "
        "v mobilní aplikaci RB nebo kontaktovat podporu.\n\n"
        f"Zdroj: {source}"
    )


def _format_payment_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for payment overview queries."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    return (
        "Raiffeisenbank v dostupných zdrojích uvádí tyto platební metody "
        "a typy plateb:\n"
        "- Tuzemské platby (v CZK v rámci ČR)\n"
        "- Zahraniční platby (SEPA pro EUR platby, SWIFT pro ostatní měny)\n"
        "- Platby kartou (online, v obchodě, mobilní platby Apple Pay/Google Pay)\n"
        "- Opakované a hromadné platby\n\n"
        "Konkrétní podmínky a poplatky závisí na typu účtu a platební metody.\n\n"
        f"Zdroj: {source}"
    )


def _format_sepa_swift_overview_answer(docs: list[Document]) -> str | None:
    """Safe direct formatter for SEPA/SWIFT overview queries."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    return (
        "SEPA platby slouží pro platby v eurech v rámci SEPA prostoru "
        "(EU + některé další země). Pro SEPA platbu potřebujete IBAN příjemce.\n\n"
        "SWIFT platby slouží pro zahraniční platby v ostatních měnách a do zemí "
        "mimo SEPA. Pro SWIFT platbu potřebujete IBAN a BIC/SWIFT kód příjemce.\n\n"
        "Konkrétní poplatky a limity závisí na typu účtu a tarifu.\n\n"
        f"Zdroj: {source}"
    )


def _product_names_from_docs(docs: list[Document]) -> list[str]:
    """Extract product names from document metadata.
    - Considers `title`, `page_title` and `document_type`.
    - Accepts document types: `product_page`, `product_catalog`, `credit_card`,
      `account_product`, `mortgage_product`.
    - Returns a deduplicated list of titles (no keyword filtering)."""
    names: set[str] = set()
    allowed_types = {
        "product_page",
        "product_catalog",
        "credit_card",
        "account_product",
        "mortgage_product",
        "pricing",
    }
    for doc in docs:
        md = doc.metadata
        doc_type = str(md.get("document_type") or "").lower()
        if doc_type not in allowed_types:
            continue
        for field in ["title", "page_title"]:
            val = md.get(field)
            if val:
                s = str(val).strip()
                # Skip obvious file names or attachment identifiers
                if s.lower().endswith('.pdf') or 'attachments' in s.lower():
                    continue
                names.add(s)
    return list(names)

def _format_product_overview_answer(docs: list[Document], query_labels: set[str] | None = None) -> str | None:
    """Safe generic formatter for any supported product overview as fallback."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

    labels = query_labels or set()

    # Insurance overview
    if "insurance" in labels:
        return (
            "Raiffeisenbank nabízí pojištění ve spolupráci s pojišťovnou UNIQA:\n\n"
            "**Pojištění k produktům:**\n"
            "- Pojištění schopnosti splácet půjčku – pro případ ztráty zaměstnání, nemoci nebo úrazu\n"
            "- Pojištění k hypotéce – životní a majetkové pojištění nemovitosti\n"
            "- Pojištění ke kreditní kartě – cestovní pojištění, pojištění nákupů\n\n"
            "**Cestovní pojištění:**\n"
            "- Cestovní pojištění NAPLNO – komplexní krytí pro cesty do zahraničí\n"
            "- Úrazové pojištění Opora – pro případ úrazu\n"
            "- Osobní strážce ke kartám – pojištění platebních karet\n\n"
            "**Individuální pojištění:**\n"
            "- Životní pojištění, majetkové pojištění, pojištění vozidel\n\n"
            f"Více informací: rb.cz/osobni/pojisteni\n\nZdroj: {source}"
        )

    # Stavební spoření
    if "stavebni_sporeni" in labels:
        return (
            "**Stavební spoření u Raiffeisenbank**\n\n"
            "Raiffeisenbank nabízí stavební spoření prostřednictvím svých partnerů. "
            "Stavební spoření kombinuje pravidelné spoření se státní podporou a možností "
            "získat výhodný stavební úvěr na bydlení.\n\n"
            "Výhody stavebního spoření:\n"
            "- Státní podpora až 2 000 Kč ročně\n"
            "- Garantované zhodnocení vkladů\n"
            "- Možnost stavebního úvěru po 6 letech spoření\n"
            "- Vhodné pro financování bydlení, rekonstrukcí a modernizací\n\n"
            f"Pro sjednání kontaktujte pobočku RB nebo zákaznickou linku.\n\nZdroj: {source}"
        )

    # Payment services overview
    if "payment_services" in labels:
        return (
            "**Platební služby Raiffeisenbank**\n\n"
            "Raiffeisenbank umožňuje tyto typy plateb:\n\n"
            "**Tuzemské platby:**\n"
            "- Jednorázová platba – ihned nebo s budoucím datem\n"
            "- Trvalý platební příkaz – pravidelné opakované platby\n"
            "- Inkaso / souhlas s inkasem – povolení pro třetí stranu strhávat platby\n"
            "- Platba na kontakt – odeslání peněz přes telefonní číslo nebo e-mail\n"
            "- Okamžitá platba – převod peněz do 10 sekund\n\n"
            "**Zahraniční platby:**\n"
            "- SEPA platba – do zemí eurozóny v EUR\n"
            "- SWIFT platba – mezinárodní platby mimo SEPA\n\n"
            "Vše zadáte v internetovém nebo mobilním bankovnictví.\n\n"
            f"Zdroj: {source}"
        )

    # Digital banking overview
    if "digital_banking" in labels:
        return (
            "**Digitální bankovnictví Raiffeisenbank**\n\n"
            "**Mobilní bankovnictví:**\n"
            "- Aplikace Raiffeisenbank pro iOS a Android\n"
            "- Správa účtů, platby, spoření a investice v mobilu\n"
            "- Přihlášení přes RB klíč, biometrii nebo PIN\n\n"
            "**Internetové bankovnictví:**\n"
            "- Přístup na ebanking.rb.cz nebo přes rb.cz\n"
            "- Přihlášení: SMS kód, RB klíč nebo Osobní klíč\n\n"
            "**RB klíč:**\n"
            "- Mobilní aplikace pro bezpečnou autorizaci plateb a přihlášení\n"
            "- Náhrada SMS kódů, vyšší bezpečnost\n\n"
            "**Placení mobilem:**\n"
            "- Apple Pay, Google Pay, placení hodinkami\n\n"
            f"Zdroj: {source}"
        )

    # RB Club
    if "rb_club" in labels:
        return (
            "**RB Club – věrnostní program Raiffeisenbank**\n\n"
            "RB Club je věrnostní program, kde získáváte odměny za aktivní využívání "
            "produktů Raiffeisenbank.\n\n"
            "Jak funguje:\n"
            "- Za platby kartou, aktivní bankovnictví a využívání produktů získáváte body\n"
            "- Body lze čerpat jako slevy, cashback nebo výhody\n"
            "- Program je dostupný klientům s aktivním osobním účtem\n\n"
            "Výhody:\n"
            "- Cashback a odměny za každodenní bankovnictví\n"
            "- Speciální nabídky a akce pro členy\n\n"
            f"Více informací: rb.cz/osobni/ucty\n\nZdroj: {source}"
        )

    # Support general
    if "support_general" in labels:
        return (
            "**Zákaznická podpora Raiffeisenbank**\n\n"
            "**Telefonní linka:**\n"
            "- 800 900 900 (zdarma, nonstop)\n"
            "- 412 440 000 (ze zahraničí)\n\n"
            "**Pobočky a bankomaty:**\n"
            "- Vyhledávač poboček a bankomatů: rb.cz → Pobočky\n"
            "- Otevírací doby se liší dle pobočky\n\n"
            "**Online podpora:**\n"
            "- Chat v mobilní aplikaci nebo na webu\n"
            "- Asistentka RAIA v mobilní aplikaci\n\n"
            "**Reklamace:**\n"
            "- Online formulář na rb.cz/reklamace\n"
            "- Na pobočce nebo telefonicky\n\n"
            f"Zdroj: {source}"
        )

    # Loans-specific overview
    if "loans" in labels or "pujcky" in labels:
        return (
            "Raiffeisenbank nabízí tyto půjčky a úvěry:\n"
            "- Minutová půjčka – až 1 200 000 Kč na cokoliv, sjednání online, 0 Kč za sjednání\n"
            "- Sloučení a převod půjček – nižší splátky, vše pod jednou střechou\n"
            "- Přečerpání účtu (kontokorent) – finanční rezerva na běžném účtu\n"
            "- Půjčka na auto – online sjednání, žádné poplatky za vedení\n"
            "- Půjčka na rekonstrukci – bez zástavy nemovitostí\n"
            "- PlatímPak – odložená platba\n\n"
            "Pro konkrétní podmínky a výši RPSN doporučuji kalkulačku na rb.cz/osobni/pujcky.\n\n"
            f"Zdroj: {source}"
        )

    # Try to extract concrete product names from metadata
    product_names = _product_names_from_docs(docs)
    if product_names:
        lines = ["Raiffeisenbank nabízí tyto produkty:"]
        lines += [f"- {name}" for name in product_names]
        lines.append("\nPro konkrétní informace otevřete detail produktu na webu RB.")
        lines.append(f"Zdroj: {source}")
        return "\n".join(lines)
    # Fallback – generic overview
    return (
        "Raiffeisenbank nabízí širokou škálu bankovních produktů a služeb:\n"
        "- Osobní a podnikatelské účty\n"
        "- Debetní a kreditní karty\n"
        "- Hypotéky a úvěry\n"
        "- Investice a spoření\n"
        "- Pojištění\n"
        "- Platební služby (tuzemské i zahraniční platby)\n\n"
        "Pro konkrétní informace doporučuji otevřít detail produktu na webu RB.\n\n"
        f"Zdroj: {source}"
    )


def format_structured_pricing_answer(docs: list[Document], max_products: int = 3) -> str:
    """Clean human formatter for high-confidence structured pricing rows."""
    grouped: dict[str, list[dict]] = {}
    ordered_docs: list[Document] = []
    for doc in docs:
        data = extract_structured_pricing_answer(doc)
        if not data:
            continue
        product = normalize_product_name(data["product_name"])
        if product not in grouped:
            if len(grouped) >= max_products:
                continue
            grouped[product] = []
        grouped[product].append(data)
        ordered_docs.append(doc)

    parts: list[str] = []
    for product, rows in grouped.items():
        parts.append(f"{product}:")
        seen_lines: set[str] = set()
        for row in rows[:3]:
            conditional = format_conditional_fee(row)
            if conditional:
                for idx, conditional_line in enumerate(conditional.splitlines()):
                    line = conditional_line if idx == 0 else conditional_line
                    if line not in seen_lines:
                        parts.append(line)
                        seen_lines.add(line)
                for tier_line in format_tiered_pricing(row):
                    if tier_line not in seen_lines:
                        parts.append(tier_line)
                        seen_lines.add(tier_line)
                continue
            tier_lines = format_tiered_pricing(row)
            if tier_lines:
                for tier_line in tier_lines:
                    if tier_line not in seen_lines:
                        parts.append(tier_line)
                        seen_lines.add(tier_line)
                continue
            line = f"* {_clean_fee_label(row['fee_type'])}: {_format_value_with_period(row['fee_value'], row.get('period', ''))}"
            if line not in seen_lines:
                parts.append(line)
                seen_lines.add(line)
        parts.append("")

    source_names = []
    for doc in ordered_docs:
        data = extract_structured_pricing_answer(doc)
        if not data:
            continue
        name = _source_display_name(data)
        if name not in source_names:
            source_names.append(name)
    if source_names:
        parts.append("Zdroj:")
        parts.extend(source_names[:2])
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Anthropic LLM wrapper
# ---------------------------------------------------------------------------

class AnthropicLLM:
    """
    Wrapper kolem Anthropic Python SDK kompatibilní s rozhraním OllamaLLM.

    Přijímá seznam LangChain BaseMessage objektů (výstup z prompt.format_messages()),
    konvertuje je do Anthropic messages.create() formátu a vrací text odpovědi.

    Prompt caching:
      Systémová zpráva (instrukce + retrieved kontext) je označena
      cache_control="ephemeral". Při opakovaných dotazech se stejným kontextem
      (follow-up otázky, stejné dokumenty) API vrátí výsledek z cache za ~0.1×
      vstupních tokenů místo plné ceny.
      Minimální cacheable prefix pro Haiku 4.5 je ~4 096 tokenů; u kratšího
      kontextu se caching tiše přeskočí bez chyby.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
    ) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        logger.info(f"AnthropicLLM inicializována (model: {model})")

    def invoke(self, messages: list[BaseMessage]) -> str:
        """
        Volá Anthropic messages.create() a vrátí text první odpovědi.

        Args:
            messages: LangChain BaseMessage list z prompt.format_messages().
                      SystemMessage → system param s cache_control
                      HumanMessage → role "user"
                      AIMessage    → role "assistant"
        """
        system_text = ""
        anthropic_messages: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        # Ephemeral cache na systémové zprávě.
        # Snižuje cenu za konverzace s opakujícím se kontextem.
        system_param = (
            [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
            if system_text
            else None
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system_param,
            messages=anthropic_messages,
        )

        usage = response.usage
        logger.debug(
            f"Anthropic usage – input: {usage.input_tokens}, "
            f"output: {usage.output_tokens}, "
            f"cache_read: {getattr(usage, 'cache_read_input_tokens', 0)}, "
            f"cache_write: {getattr(usage, 'cache_creation_input_tokens', 0)}"
        )

        return response.content[0].text

    def stream(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        """Streaming variant of invoke(). Yields text tokens as they arrive."""
        system_text = ""
        anthropic_messages: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        system_param = (
            [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
            if system_text
            else None
        )

        with self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system_param,
            messages=anthropic_messages,
            stream=True,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield event.delta.text


# ---------------------------------------------------------------------------
# Google Gemini – auto-discovery + LLM wrapper
# ---------------------------------------------------------------------------

# Prioritizovaný seznam modelů pro automatický výběr.
# client.models.list() vrací jména ve formátu "models/gemini-*";
# pro API volání se používá jméno BEZ prefixu "models/".
_GEMINI_MODEL_PRIORITY: list[str] = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
]

# Vzory modelů k přeskočení (embedding, TTS, vision-only, deprecated)
_GEMINI_SKIP_PATTERNS = ("embed", "tts", "vision", "aqa", "imagen", "deprecated")


def discover_gemini_model(api_key: str) -> str:
    """
    Dotáže se Gemini API na seznam dostupných modelů a vrátí nejlepší
    dostupný model podporující generateContent.

    Algoritmus:
      1. Zavolá client.models.list() a extrahuje jména bez prefixu "models/"
      2. Projde _GEMINI_MODEL_PRIORITY → vrátí první, který je dostupný
      3. Pokud žádný z priority listu není dostupný, vrátí první flash model
         s generateContent nebo count_tokens capability
      4. Pokud ani to selže, vrátí výchozí "gemini-2.0-flash"

    Args:
        api_key: Platný Gemini API klíč.

    Returns:
        Název modelu pro použití v generate_content() (bez prefixu "models/").
    """
    from google import genai

    try:
        client = genai.Client(api_key=api_key)

        # Načteme dostupné modely a normalizujeme jména (strip "models/" prefix)
        available: list[str] = []
        for m in client.models.list():
            raw_name: str = m.name or ""
            short_name = raw_name.removeprefix("models/")

            # Přeskočíme modely bez jména nebo s nevhodným vzorem
            if not short_name:
                continue
            if any(pat in short_name.lower() for pat in _GEMINI_SKIP_PATTERNS):
                continue

            available.append(short_name)

        logger.debug(f"Dostupné Gemini modely: {available}")

        # Krok 1: zkontrolujeme priority list
        for preferred in _GEMINI_MODEL_PRIORITY:
            if preferred in available:
                logger.info(f"Auto-discovery: zvolen model '{preferred}'")
                return preferred

        # Krok 2: první flash model v dostupných
        flash_models = [m for m in available if "flash" in m.lower()]
        if flash_models:
            chosen = flash_models[0]
            logger.info(f"Auto-discovery: zvolen první flash model '{chosen}'")
            return chosen

        # Krok 3: bezpečný fallback
        logger.warning("Auto-discovery nenašla vhodný model, používám fallback 'gemini-2.0-flash'")

    except Exception as exc:
        logger.warning(f"Auto-discovery selhala: {exc} – používám výchozí model z konfigurace")

    return "gemini-2.0-flash"


class GeminiLLM:
    """
    Wrapper kolem Google Gemini SDK (google-genai) kompatibilní s rozhraním OllamaLLM.

    Při inicializaci volitelně zavolá discover_gemini_model() pro automatický
    výběr nejlepšího dostupného modelu – viz config.GEMINI_MODEL.

    Konverze LangChain BaseMessage → Gemini Contents:
      SystemMessage → GenerateContentConfig.system_instruction
      HumanMessage  → role "user"
      AIMessage     → role "model"  (Gemini používá "model", ne "assistant")

    Poznámka: google-generativeai je deprecated; tento wrapper používá
    officiální nástupce google-genai (from google import genai).
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
    ) -> None:
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._max_tokens = max_tokens
        self._temperature = temperature

        # Pokud je model nastaven na výchozí hodnotu, ověříme dostupnost
        # přes API; jinak respektujeme explicitní nastavení uživatele.
        if model == "gemini-2.0-flash":
            self._model = discover_gemini_model(api_key)
        else:
            self._model = model

        logger.info(f"GeminiLLM inicializována (model: {self._model})")

    def invoke(self, messages: list[BaseMessage]) -> str:
        """
        Volá Gemini generate_content a vrátí text odpovědi.

        Args:
            messages: LangChain BaseMessage list z prompt.format_messages().
                      SystemMessage → system_instruction v config
                      HumanMessage  → role "user"
                      AIMessage     → role "model"
        """
        from google.genai import types

        system_text = ""
        contents: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif isinstance(msg, AIMessage):
                # Gemini používá "model" jako roli asistenta, ne "assistant"
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        generation_config = types.GenerateContentConfig(
            system_instruction=system_text or None,
            max_output_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=generation_config,
        )

        return response.text

    def stream(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        """Streaming variant of invoke(). Yields text tokens as they arrive."""
        from google.genai import types

        system_text = ""
        contents: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif isinstance(msg, AIMessage):
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        generation_config = types.GenerateContentConfig(
            system_instruction=system_text or None,
            max_output_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        stream = self._client.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=generation_config,
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text


# ---------------------------------------------------------------------------
# OpenAI LLM wrapper
# ---------------------------------------------------------------------------

class OpenAILLM:
    """
    Wrapper kolem OpenAI Chat Completions API kompatibilní s rozhraním
    OllamaLLM / AnthropicLLM / GeminiLLM.

    Features:
      - Chat Completions API (messages → response)
      - Retry s exponenciálním backoffem (nativní podpora v openai SDK)
      - Rate-limit handling (429) s fallback model
      - Timeout konfigurovatelný přes config.LLM_TIMEOUT
      - Automatický fallback na gpt-4o-mini pokud primární model selže

    Konverze LangChain BaseMessage → OpenAI messages:
      SystemMessage → role "system"
      HumanMessage  → role "user"
      AIMessage     → role "assistant"
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
        timeout: int,
        max_retries: int,
        fallback_model: str,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model
        self._fallback_model = fallback_model
        self._max_tokens = max_tokens
        self._temperature = temperature
        logger.info(
            f"OpenAILLM inicializována "
            f"(model: {model}, fallback: {fallback_model}, "
            f"timeout: {timeout}s, retry: {max_retries}x)"
        )

    def invoke(self, messages: list[BaseMessage]) -> str:
        """
        Volá OpenAI Chat Completions a vrátí text první odpovědi.

        Prio 1: primární model (config.OPENAI_CHAT_MODEL)
        Prio 2: fallback model (config.OPENAI_CHAT_FALLBACK_MODEL)

        Args:
            messages: LangChain BaseMessage list z prompt.format_messages().

        Returns:
            Text odpovědi asistenta.

        Raises:
            openai.RateLimitError: Pokud oba modely selžou na rate limit.
            openai.APIStatusError: Pokud oba modely selžou na API chybu.
        """
        from openai import APIStatusError, RateLimitError

        openai_messages: list[dict] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                openai_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                openai_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                openai_messages.append({"role": "assistant", "content": msg.content})

        models_to_try = [self._model]
        if self._fallback_model and self._fallback_model != self._model:
            models_to_try.append(self._fallback_model)

        last_error: Exception | None = None

        for attempt, model in enumerate(models_to_try):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=openai_messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )
                content = response.choices[0].message.content or ""
                if attempt > 0:
                    logger.warning(
                        f"OpenAI fallback úspěšný: {self._model} → {model} "
                        f"({type(last_error).__name__}: {last_error})"
                    )
                else:
                    logger.debug(f"OpenAI response ({model}): {len(content)} znaků")
                return content

            except RateLimitError as e:
                last_error = e
                logger.warning(
                    f"OpenAI rate limit ({model}): {e}"
                )
                if model == self._model and self._fallback_model:
                    logger.info(f"⤴ Fallback na {self._fallback_model}")
                    continue
                logger.error("OpenAI rate limit – oba modely selhaly")
                raise

            except APIStatusError as e:
                last_error = e
                # 400 = bad request, 401 = auth, 403 = forbidden, 404 = not found
                # 429 = rate limit (caught above), 500 = server error
                if (
                    e.status_code in (400, 401, 403, 404)
                    and model == self._model
                    and self._fallback_model
                ):
                    logger.warning(
                        f"OpenAI API error ({model}, {e.status_code}): {e.message}"
                        f"⤴ Fallback na {self._fallback_model}"
                    )
                    continue
                logger.error(
                    f"OpenAI API error ({model}, {e.status_code}): {e.message}"
                )
                raise

            except Exception as e:
                last_error = e
                logger.warning(
                    f"OpenAI neočekávaná chyba ({model}): {e}"
                )
                if model == self._model and self._fallback_model:
                    logger.info(f"⤴ Fallback na {self._fallback_model}")
                    continue
                raise

        raise last_error or RuntimeError(
            "OpenAILLM: všechny pokusy selhaly (primary + fallback)"
        )

    def stream(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        """Streaming variant of invoke(). Yields text tokens as they arrive.

        Falls back to non-streaming invoke for retry cases (rate-limit, API errors)
        to maintain reliability — the fallback response is yielded as one token.
        """
        from openai import APIStatusError, RateLimitError

        openai_messages: list[dict] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                openai_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                openai_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                openai_messages.append({"role": "assistant", "content": msg.content})

        models_to_try = [self._model]
        if self._fallback_model and self._fallback_model != self._model:
            models_to_try.append(self._fallback_model)

        last_error: Exception | None = None

        for attempt, model in enumerate(models_to_try):
            try:
                stream = self._client.chat.completions.create(
                    model=model,
                    messages=openai_messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        yield delta
                if attempt > 0:
                    logger.warning(
                        f"OpenAI stream fallback úspěšný: {self._model} → {model}"
                    )
                return  # success

            except (RateLimitError, APIStatusError) as e:
                last_error = e
                logger.warning(f"OpenAI stream error ({model}): {e}")
                if model == self._model and self._fallback_model:
                    logger.info(f"⤴ Stream fallback na {self._fallback_model}")
                    continue
                # Last resort: yield full invoke response as one token
                logger.warning("Stream fallback vyčerpán — vracím full invoke")
                yield self.invoke(messages)
                return

            except Exception as e:
                last_error = e
                logger.warning(f"OpenAI stream neočekávaná chyba ({model}): {e}")
                if model == self._model and self._fallback_model:
                    logger.info(f"⤴ Stream fallback na {self._fallback_model}")
                    continue
                yield self.invoke(messages)
                return

        # All models failed — yield full invoke as last resort
        logger.error("OpenAI stream: všechny modely selhaly, fallback na invoke")
        yield self.invoke(messages)


# ---------------------------------------------------------------------------
# Factory – výběr backendu dle konfigurace
# ---------------------------------------------------------------------------

def _build_llm(model_override: str | None = None) -> OllamaLLM | AnthropicLLM:
    """
    Vytvoří LLM instanci dle config.LLM_BACKEND.

    Returns:
        OllamaLLM  – pokud LLM_BACKEND == "ollama"
        AnthropicLLM – pokud LLM_BACKEND == "anthropic"

    Raises:
        ValueError: Při neznámém backendu nebo chybějícím ANTHROPIC_API_KEY.
    """
    backend = config.LLM_BACKEND.lower()

    if backend == "ollama":
        t_import = time.perf_counter()
        from langchain_ollama import OllamaLLM
        logger.info(f"import_timing.langchain_ollama ms={(time.perf_counter() - t_import) * 1000:.1f}")
        return OllamaLLM(
            model=config.LLM_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            num_predict=config.LLM_MAX_TOKENS,
        )

    if backend == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise ValueError(
                "LLM_BACKEND='anthropic' vyžaduje nastavený ANTHROPIC_API_KEY v .env"
            )
        return AnthropicLLM(
            model=config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        )

    if backend == "gemini":
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "LLM_BACKEND='gemini' vyžaduje nastavený GEMINI_API_KEY v .env"
            )
        return GeminiLLM(
            model=config.GEMINI_MODEL,
            api_key=config.GEMINI_API_KEY,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        )

    if backend == "openai":
        if not config.OPENAI_API_KEY:
            raise ValueError(
                "LLM_BACKEND='openai' vyžaduje nastavený OPENAI_API_KEY v .env"
            )
        model_name = model_override if model_override else config.OPENAI_CHAT_MODEL
        return OpenAILLM(
            model=model_name,
            api_key=config.OPENAI_API_KEY,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_TIMEOUT,
            max_retries=config.LLM_MAX_RETRIES,
            fallback_model=config.OPENAI_CHAT_FALLBACK_MODEL,
        )

    raise ValueError(
        f"Neznámý LLM_BACKEND='{config.LLM_BACKEND}'. "
        f"Povolené hodnoty: 'ollama', 'anthropic', 'gemini', 'openai'."
    )


# ---------------------------------------------------------------------------
# BankingRAGChain
# ---------------------------------------------------------------------------

class BankingRAGChain:
    """
    Hlavní RAG chain pro Raiffeisenbank chatbot.

    Backend se volí automaticky dle config.LLM_BACKEND:
      - "ollama"    → lokální LLM (Mistral/Llama), žádné cloudové volání
      - "anthropic" → claude-haiku-4-5 s prompt cachingem, rychlý a levný

    Použití:
        chain = BankingRAGChain()
        result = chain.ask("Jaký je poplatek za vedení účtu?")
        print(result["answer"])

        # Konverzační mód (výchozí)
        chain = BankingRAGChain(conversational=True)
        chain.ask("Co je eKonto?")
        chain.ask("Jaké jsou jeho poplatky?")  # navazuje na kontext
    """

    def __init__(self, conversational: bool = True) -> None:
        self.conversational = conversational
        self.chat_history: list[BaseMessage] = []
        self.pending_clarification: str | None = None
        self.clarification_context: dict | None = None
        self.resolved_product: str | None = None
        self.resolved_intent: str | None = None
        # Priority 4: Semantic session context
        self.session_context: dict[str, str | None] = {
            "current_domain": None,
            "current_product": None,
            "current_intent": None,
            "last_clarification": None,
            "resolved_product": None,
            "resolved_segment": None,
        }
        # Conversational entity memory (P1 — clarification resolution)
        self.unresolved_product: str | None = None
        self.unresolved_product_type: str | None = None
        self.clarification_candidates: list[str] | None = None
        self.last_canonical_product: str | None = None

        self._llm = _build_llm()
        self._fast_llm = _build_llm(model_override=config.FAST_MODEL)
        t_import = time.perf_counter()
        from src.retrieval.retriever import BankingRetriever
        logger.info(f"import_timing.retrieval.BankingRetriever ms={(time.perf_counter() - t_import) * 1000:.1f}")
        self._retriever = BankingRetriever()

        if config.LLM_BACKEND == "anthropic":
            backend_info = f"anthropic/{config.ANTHROPIC_MODEL}"
        elif config.LLM_BACKEND == "gemini":
            backend_info = f"gemini/{config.GEMINI_MODEL}"
        elif config.LLM_BACKEND == "openai":
            backend_info = f"openai/{config.OPENAI_CHAT_MODEL} (fallback: {config.OPENAI_CHAT_FALLBACK_MODEL})"
        else:
            backend_info = f"ollama/{config.LLM_MODEL}"
        logger.info(
            f"BankingRAGChain inicializována "
            f"(backend: {backend_info}, konverzační: {conversational})"
        )

    def _rewrite_query(self, question: str) -> str:
        """
        Přeformuluje dotaz s ohledem na historii konverzace.
        Používá se pouze pokud existuje neprázdná historie.
        """
        if not self.chat_history:
            return question

        # Pricing dotazy jsou self-contained — rewrite by je kontaminoval
        _q = question.lower()
        _PRICING_SIGNALS = ("kolik stojí", "kolik stoji", "cena", "poplatek", "poplatky", "stojí", "stoji", "sazba", "úrok", "zdarma")
        if any(s in _q for s in _PRICING_SIGNALS):
            return question

        messages = get_query_rewrite_prompt().format_messages(
            chat_history=self.chat_history,
            question=question,
        )
        # Bypass any streaming wrapper (_StreamingInvoker) — rewrite tokens must
        # not be buffered into the SSE answer stream and must not fire llm_started
        # prematurely (which would cause the rewrite text to appear as the answer).
        _rewrite_llm = getattr(self._llm, "_real_llm", self._llm)
        rewritten = _rewrite_llm.invoke(messages)
        # OllamaLLM vrátí str, AnthropicLLM také vrátí str
        rewritten_text = (rewritten if isinstance(rewritten, str) else str(rewritten)).strip()

        # Guard 1: rewrite vrátil identický nebo téměř stejný dotaz → originál
        # (Povolujeme rewrites co končí '?' — jsou to validní přeformulované otázky)
        if rewritten_text.strip().lower() == question.strip().lower():
            logger.debug(f"Query rewrite guard (identical): revert '{rewritten_text[:60]}'")
            return question

        # Guard 2: rewrite je výrazně delší než originál → originál
        if len(rewritten_text) > len(question) * 1.5:
            logger.debug(f"Query rewrite guard (too long): revert '{rewritten_text[:60]}'")
            return question

        # Guard 3: rewrite neobsahuje žádné klíčové slovo z originálního dotazu → originál
        original_words = {w.lower() for w in question.split() if len(w) > 3}
        rewritten_words = rewritten_text.lower()
        if original_words and not any(w in rewritten_words for w in original_words):
            logger.debug(f"Query rewrite guard (no keywords): revert '{rewritten_text[:60]}'")
            return question

        logger.debug(f"Query rewrite: '{question}' → '{rewritten_text}'")
        return rewritten_text

    def ask(self, question: str) -> dict:
        """
        Položí otázku a vrátí odpověď s metadaty.

        Args:
            question: Uživatelský dotaz v češtině.

        Returns:
            Dict s klíči:
              - answer (str): Vygenerovaná odpověď
              - sources (list[Document]): Použité zdroje
              - rewritten_query (str): Přeformulovaný dotaz (pokud se liší)
        """
        t_ask = time.perf_counter()
        # Priority 4: Initialize session debug (populated by post-processing)
        self._session_debug: dict[str, Any] = {}

        # 0. System/orchestration intents are evaluated on the raw user turn so
        # conversational query rewriting cannot contaminate assistant identity or
        # urgent guided flows with previous banking context.
        raw_resolved = _resolve_pending_clarification(question, getattr(self, "clarification_context", None))
        if raw_resolved:
            retrieval_query, self.resolved_product, self.resolved_intent = raw_resolved
            self.pending_clarification = None
            self.clarification_context = None
            # Store resolved product in entity memory for follow-up continuity
            self.last_canonical_product = raw_resolved[1]
            self.unresolved_product = None
            self.clarification_candidates = None
        elif _identity_intent(question):
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("high", "deterministic assistant identity route")
            return {
                "answer": IDENTITY_RESPONSE,
                "sources": [],
                "rewritten_query": question,
                "retrieval_debug": _debug_with_ux(_identity_debug(question), ux),
                "answer_strategy": "identity_direct",
                "answer_confidence": "high",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }
        elif (catalog_intent := _soft_guidance_intent(question)) and catalog_intent.startswith("catalog_") and _soft_guidance_answer(catalog_intent):
            catalog_answer = _soft_guidance_answer(catalog_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", f"catalog soft guidance for {catalog_intent}", confidence_factors={"soft_guidance_used": True})
            logger.info(f"Answer strategy: soft_guidance_direct ({catalog_intent}, pre-retrieval catalog)")
            return {
                "answer": catalog_answer,
                "sources": [],
                "rewritten_query": question,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "soft_guidance",
                    "retrieval_skipped": True,
                    "soft_guidance_intent": catalog_intent,
                }], ux),
                "answer_strategy": "soft_guidance_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }
        elif (raw_guided_intent := _guided_flow_intent(question)):
            answer = _guided_flow_answer(raw_guided_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", f"deterministic guided flow for {raw_guided_intent}")
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": question,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "guided_flow",
                    "retrieval_skipped": True,
                    "guided_flow": raw_guided_intent,
                }], ux),
                "answer_strategy": "guided_flow_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }
        elif (raw_procedural_intent := _procedural_flow_intent(question)):
            answer = _procedural_flow_answer(raw_procedural_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", f"deterministic procedural flow for {raw_procedural_intent}", confidence_factors={"authority_boost_used": True, "soft_guidance_used": True})
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": question,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "procedural_flow",
                    "retrieval_skipped": True,
                    "procedural_flow": raw_procedural_intent,
                }], ux),
                "answer_strategy": "procedural_flow_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }
        elif (raw_unsupported_intent := _unsupported_intent(question)):
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("low", f"unsupported topic outside reliable RB knowledge boundary: {raw_unsupported_intent}", unsupported_reason=raw_unsupported_intent)
            return {
                "answer": UNSUPPORTED_RESPONSE,
                "sources": [],
                "rewritten_query": question,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "unsupported",
                    "retrieval_skipped": True,
                    "unsupported_intent": raw_unsupported_intent,
                }], ux),
                "answer_strategy": "unsupported_direct",
                "answer_confidence": "low",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }
        else:
            retrieval_query = ""

        # 1. Query rewriting pro follow-up otázky (jen s historií)
        t_rewrite = time.perf_counter()
        if not retrieval_query:
            retrieval_query = (
                self._rewrite_query(question)
                if self.conversational and self.chat_history
                else question
            )

            # Context guard: krátké ambiguózní follow-upy dostanou prefix z posledního kontextu
            _CONTEXT_SIGNALS = {
                "raia": "RAIA",
                "asistentk": "RAIA asistentka",
                "bankovn": "bankovní identita RB",
                "identit": "bankovní identita RB",
                "rb klic": "RB klíč",
                "rb klíč": "RB klíč",
            }
            def _strip_diacritics(text: str) -> str:
                repl = str.maketrans("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ", "acdeeinorstuuyzACDEEINORSTUUYZ")
                return text.translate(repl).lower()

            if self.chat_history and len(retrieval_query.split()) <= 6:
                last_ai = next(
                    (m.content for m in reversed(self.chat_history)
                     if hasattr(m, "content") and m.__class__.__name__ == "AIMessage"),
                    ""
                )
                last_ai_norm = _strip_diacritics(last_ai)
                for signal, prefix in _CONTEXT_SIGNALS.items():
                    signal_norm = _strip_diacritics(signal)
                    if signal_norm in last_ai_norm:
                        original_rq = retrieval_query
                        retrieval_query = f"{prefix}: {retrieval_query}"
                        logger.debug(f"Context guard: '{original_rq}' → '{retrieval_query}'")
                        break

        rewrite_ms = (time.perf_counter() - t_rewrite) * 1000
        if self.chat_history:  # rewriting probíhá jen pokud existuje historie
            logger.info(f"⏱ Query rewriting: {rewrite_ms:.0f}ms")

        # 1a. Resolve short-lived clarification state before new retrieval.
        resolved = _resolve_pending_clarification(retrieval_query, getattr(self, "clarification_context", None))
        if resolved:
            retrieval_query, self.resolved_product, self.resolved_intent = resolved
            self.pending_clarification = None
            self.clarification_context = None

        # 1b. Explicit identity/system route before any retrieval.
        if _identity_intent(retrieval_query):
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("high", "deterministic assistant identity route")
            return {
                "answer": IDENTITY_RESPONSE,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux(_identity_debug(retrieval_query), ux),
                "answer_strategy": "identity_direct",
                "answer_confidence": "high",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        # 1c. Product clarification state for ambiguous eKonto pricing.
        if _is_ekonto_ambiguous_pricing(retrieval_query):
            self.pending_clarification = "ekonto_pricing"
            self.clarification_context = {"type": "ekonto_pricing", "original_query": retrieval_query}
            self.unresolved_product = "ekonto"
            self.unresolved_product_type = "pricing"
            self.clarification_candidates = ["osobní eKonto (osobní)", "podnikatelské eKonto (podnikatelské)", "eKonto SMART (smart)", "eKonto KOMPLET (komplet)"]
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", "ambiguous eKonto product requires product segment clarification", clarification_required=True)
            return {
                "answer": EKONTO_CLARIFICATION,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "clarification",
                    "retrieval_skipped": True,
                    "pending_clarification": self.pending_clarification,
                    "clarification_context": self.clarification_context,
                    "unresolved_product": self.unresolved_product,
                    "clarification_candidates": self.clarification_candidates,
                }], ux),
                "answer_strategy": "clarification_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        # Catalog soft guidance: fire before retrieval for product listing queries.
        catalog_intent_main = _soft_guidance_intent(question)
        if catalog_intent_main and catalog_intent_main.startswith("catalog_"):
            catalog_answer_main = _soft_guidance_answer(catalog_intent_main)
            if catalog_answer_main:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", f"catalog soft guidance for {catalog_intent_main}", confidence_factors={"soft_guidance_used": True})
                logger.info(f"Answer strategy: soft_guidance_direct ({catalog_intent_main}, pre-retrieval catalog main)")
                return {
                    "answer": catalog_answer_main,
                    "sources": [],
                    "rewritten_query": retrieval_query,
                    "retrieval_debug": _debug_with_ux([{
                        "retrieval_route": "soft_guidance",
                        "retrieval_skipped": True,
                        "soft_guidance_intent": catalog_intent_main,
                    }], ux),
                    "answer_strategy": "soft_guidance_direct",
                    "answer_confidence": "medium",
                    **ux,
                    "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
                }

        guided_intent = _guided_flow_intent(retrieval_query)
        if guided_intent:
            answer = _guided_flow_answer(guided_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", f"deterministic guided flow for {guided_intent}")
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "guided_flow",
                    "retrieval_skipped": True,
                    "guided_flow": guided_intent,
                }], ux),
                "answer_strategy": "guided_flow_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        # Priority 3: Procedural flow routing (after guided flow, before unsupported).
        procedural_intent = _procedural_flow_intent(retrieval_query)
        if procedural_intent:
            answer = _procedural_flow_answer(procedural_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", f"deterministic procedural flow for {procedural_intent}", confidence_factors={"authority_boost_used": True, "soft_guidance_used": True})
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "procedural_flow",
                    "retrieval_skipped": True,
                    "procedural_flow": procedural_intent,
                }], ux),
                "answer_strategy": "procedural_flow_direct",
                "answer_confidence": "medium",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        unsupported_intent = _unsupported_intent(retrieval_query)
        if unsupported_intent:
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("low", f"unsupported topic outside reliable RB knowledge boundary: {unsupported_intent}", unsupported_reason=unsupported_intent)
            return {
                "answer": UNSUPPORTED_RESPONSE,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "unsupported",
                    "retrieval_skipped": True,
                    "unsupported_intent": unsupported_intent,
                }], ux),
                "answer_strategy": "unsupported_direct",
                "answer_confidence": "low",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        # 1d. Explicit ambiguity/advisory policy before retrieval.
        ambiguity_intent = _ambiguity_intent(retrieval_query)
        if ambiguity_intent:
            answer = _clarification_answer(ambiguity_intent)
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta("medium", "explicit ambiguity policy requires clarification", clarification_required=True)
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "clarification",
                    "intent_class": "ambiguous" if ambiguity_intent != "account_advisory" else "advisory",
                    "ambiguity_intent": ambiguity_intent,
                    "faq_priority_used": False,
                    "metadata_boost_reason": [],
                    "rewritten_query": retrieval_query,
                }], ux),
                "answer_strategy": "clarification_direct",
                "answer_confidence": "high",
                **ux,
                "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
            }

        # Priority 1e: Comparison routing (pre-retrieval, deterministic).
        comparison_intent = _comparison_intent(retrieval_query)
        if comparison_intent:
            from src.generation.comparison_engine import (
                detect_comparison_entities,
                format_comparison_answer,
            )
            from src.generation.constants import RouteStrategy
            entities = detect_comparison_entities(retrieval_query)
            if entities:
                answer = format_comparison_answer(entities)
                if answer:
                    total_ms = (time.perf_counter() - t_ask) * 1000
                    ux = _ux_meta("medium", "deterministic comparison answer from product registry")
                    logger.info(f"Answer strategy: {RouteStrategy.COMPARISON_DIRECT} ({' vs '.join(entities)})")
                    return {
                        "answer": answer,
                        "sources": [],
                        "rewritten_query": retrieval_query,
                        "retrieval_debug": _debug_with_ux([{
                            "retrieval_route": "comparison",
                            "comparison_entities": entities,
                            "retrieval_skipped": True,
                        }], ux),
                        "answer_strategy": RouteStrategy.COMPARISON_DIRECT,
                        "answer_confidence": "medium",
                        **ux,
                        "timing_ms": {"retrieval": 0, "total": round(total_ms), "llm": 0},
                    }

        # 2. Retrieval
        t_retrieval = time.perf_counter()
        try:
            source_docs: list[Document] = self._retriever.invoke(retrieval_query)
        except TimeoutError:
            retrieval_ms = (time.perf_counter() - t_retrieval) * 1000
            total_ms = (time.perf_counter() - t_ask) * 1000
            ux = _ux_meta(
                "low",
                "empty retrieval resilience: retrieval_timeout",
                unsupported_reason="retrieval_timeout",
                confidence_factors={
                    "retrieval_weak": True,
                    "fallback_used": True,
                    "source_count": 0,
                    "resilience_category": "retrieval_timeout",
                    "escalation_strategy": "retry_or_contact_support",
                },
            )
            return {
                "answer": RESILIENCE_RESPONSES["retrieval_timeout"],
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "unsupported",
                    "retrieval_skipped": False,
                    "resilience_category": "retrieval_timeout",
                    "resilience_strategy": "timeout_safe_fallback",
                }], ux),
                "answer_strategy": "retrieval_timeout_fallback",
                "answer_confidence": "low",
                **ux,
                "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
            }
        retrieval_ms = (time.perf_counter() - t_retrieval) * 1000

        if not source_docs:
            overview_profile = classify_query(retrieval_query)
            if "product_overview" in overview_profile.labels and "supported_domain" in overview_profile.labels:
                # Supported overview query with empty retrieval — still provide a safe overview.
                overview_answer = _format_product_overview_answer([], query_labels=overview_profile.labels)
                if overview_answer:
                    total_ms = (time.perf_counter() - t_ask) * 1000
                    ux = _ux_meta("medium", "supported product overview with safe fallback (retrieval empty)")
                    logger.info("Answer strategy: product_overview_direct (retrieval empty, safe overview)")
                    return {
                        "answer": overview_answer,
                        "sources": [],
                        "rewritten_query": retrieval_query,
                        "answer_strategy": "product_overview_direct",
                        "answer_confidence": "medium",
                        "retrieval_debug": _debug_with_ux([{
                            "retrieval_route": "product_overview",
                            "retrieval_skipped": False,
                            "overview_route_used": True,
                            "supported_domain_detected": True,
                            "unsupported_guard_bypassed": True,
                            "fallback_overview_retrieval_used": True,
                            "rewritten_query": retrieval_query,
                        }], ux),
                        **ux,
                        "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                    }
            # Priority 2: Soft guidance — for common FAQ/procedural queries with
            # weak retrieval, still provide a safe answer instead of unsupported.
            # Use original `question`, not `retrieval_query` — LLM rewrites can
            # introduce topic drift (e.g. rewrites of "Co je Platím pak?" in RAIA
            # context may contain "raia"), causing the wrong soft-guidance answer
            # to be returned and cached under the original question's cache key.
            soft_intent = _soft_guidance_intent(question)
            if soft_intent:
                soft_answer = _soft_guidance_answer(soft_intent)
                if soft_answer:
                    total_ms = (time.perf_counter() - t_ask) * 1000
                    ux = _ux_meta("medium", f"soft guidance for {soft_intent} (retrieval empty)", confidence_factors={"authority_boost_used": True, "soft_guidance_used": True, "retrieval_weak": True, "fallback_used": True, "source_count": 0})
                    logger.info(f"Answer strategy: soft_guidance_direct ({soft_intent}, retrieval empty)")
                    return {
                        "answer": soft_answer,
                        "sources": [],
                        "rewritten_query": retrieval_query,
                        "answer_strategy": "soft_guidance_direct",
                        "answer_confidence": "medium",
                        "retrieval_debug": _debug_with_ux([{
                            "retrieval_route": "soft_guidance",
                            "retrieval_skipped": False,
                            "soft_guidance_intent": soft_intent,
                            "retrieval_soft_fail": True,
                            "rewritten_query": retrieval_query,
                        }], ux),
                        **ux,
                        "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                    }
            last_governance_meta = getattr(self._retriever, "last_governance_meta", {}) or {}
            forced_category = None
            if (
                last_governance_meta.get("resilience_strategy") == "governance_suppressed"
                or (
                    last_governance_meta.get("retrieval_collapse_detected")
                    and int(last_governance_meta.get("governance_removed_count") or 0) > 0
                )
            ):
                forced_category = "governance_suppressed"
            category, answer, ux = _empty_retrieval_resilience(classify_query(retrieval_query), forced_category=forced_category)
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{
                    "retrieval_route": "unsupported" if category == "unsupported_domain" else "supported_missing_data",
                    "retrieval_skipped": False,
                    "resilience_category": category,
                    "resilience_strategy": category,
                    "final_source_count": 0,
                    "governance_removed_count": last_governance_meta.get("governance_removed_count"),
                    "governance_suppressed_count": last_governance_meta.get("suppressed_count"),
                    "retrieval_collapse_detected": last_governance_meta.get("retrieval_collapse_detected"),
                }], ux),
                "answer_strategy": f"{category}_fallback",
                "answer_confidence": "low",
                **ux,
            }

        top_doc = source_docs[0]
        structured_docs = _structured_pricing_docs(source_docs)

        if top_doc.metadata.get("pricing_safe_fallback") is True:
            total_ms = (time.perf_counter() - t_ask) * 1000
            answer_text = str(top_doc.page_content or top_doc.metadata.get("fee_type") or "").strip()
            ux = _ux_meta(
                "low",
                "safe pricing fallback: pricing docs exist but no explicit canonical row",
                confidence_factors={
                    "pricing_grounding": False,
                    "pricing_row_found": False,
                    "pricing_canonical_used": top_doc.metadata.get("pricing_canonical_used", False),
                    "source_count": len(source_docs),
                },
            )
            logger.info("Answer strategy: pricing_safe_fallback (LLM skipped)")
            return {
                "answer": answer_text,
                "sources": source_docs,
                "rewritten_query": retrieval_query,
                "answer_strategy": "pricing_safe_fallback",
                "answer_confidence": "low",
                "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "pricing_safe_fallback"), ux),
                **ux,
                "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
            }

        # Priority 4: Session context — inherit from previous turn for short follow-ups
        inherited_product, inherited_intent = self._check_session_inheritance(retrieval_query)
        if inherited_product or inherited_intent:
            logger.info(
                f"Session context inherited: product={inherited_product}, intent={inherited_intent}"
            )

        query_profile = classify_query(retrieval_query)
        # Update session context with current query profile
        self._update_session_context(query_profile)
        session_debug = self._get_session_debug(inherited_product, inherited_intent)
        # Store session debug on instance so main.py reads it after ask() returns
        self._session_debug = session_debug

        if "card_overview" in query_profile.labels:
            overview_answer = _format_card_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported card overview route with source-backed overview")
                logger.info("Answer strategy: card_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "card_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "card_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "account_overview" in query_profile.labels and "savings" not in query_profile.labels:
            overview_answer = _format_account_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported account overview route with safe overview")
                logger.info("Answer strategy: account_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "account_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "account_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "mortgage_overview" in query_profile.labels:
            # Prefer catalog soft_guidance over generic overview for explicit listing queries
            _mg_catalog = _soft_guidance_intent(question)
            if _mg_catalog and _mg_catalog.startswith("catalog_"):
                _mg_ans = _soft_guidance_answer(_mg_catalog)
                if _mg_ans:
                    total_ms = (time.perf_counter() - t_ask) * 1000
                    ux = _ux_meta("medium", f"catalog soft guidance override ({_mg_catalog})", confidence_factors={"soft_guidance_used": True})
                    logger.info(f"Answer strategy: soft_guidance_direct ({_mg_catalog}, overrides mortgage_overview_direct)")
                    return {"answer": _mg_ans, "sources": [], "rewritten_query": retrieval_query, "answer_strategy": "soft_guidance_direct", "answer_confidence": "medium", "retrieval_debug": _debug_with_ux([{"retrieval_route": "soft_guidance", "retrieval_skipped": False, "soft_guidance_intent": _mg_catalog}], ux), **ux, "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0}}
            overview_answer = _format_mortgage_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported mortgage overview route with safe overview")
                logger.info("Answer strategy: mortgage_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "mortgage_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "mortgage_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "investment_overview" in query_profile.labels:
            # Prefer catalog soft_guidance over generic overview for explicit listing queries
            _iv_catalog = _soft_guidance_intent(question)
            if _iv_catalog and _iv_catalog.startswith("catalog_"):
                _iv_ans = _soft_guidance_answer(_iv_catalog)
                if _iv_ans:
                    total_ms = (time.perf_counter() - t_ask) * 1000
                    ux = _ux_meta("medium", f"catalog soft guidance override ({_iv_catalog})", confidence_factors={"soft_guidance_used": True})
                    logger.info(f"Answer strategy: soft_guidance_direct ({_iv_catalog}, overrides investment_overview_direct)")
                    return {"answer": _iv_ans, "sources": [], "rewritten_query": retrieval_query, "answer_strategy": "soft_guidance_direct", "answer_confidence": "medium", "retrieval_debug": _debug_with_ux([{"retrieval_route": "soft_guidance", "retrieval_skipped": False, "soft_guidance_intent": _iv_catalog}], ux), **ux, "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0}}
            overview_answer = _format_investment_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported investment overview route with safe overview")
                logger.info("Answer strategy: investment_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "investment_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "investment_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "rb_key_overview" in query_profile.labels:
            overview_answer = _format_rb_key_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported RB klíč overview route with safe overview")
                logger.info("Answer strategy: rb_key_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "rb_key_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "rb_key_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "payment_overview" in query_profile.labels:
            overview_answer = _format_payment_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported payment overview route with safe overview")
                logger.info("Answer strategy: payment_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "payment_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "payment_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "sepa_swift_overview" in query_profile.labels:
            overview_answer = _format_sepa_swift_overview_answer(source_docs)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported SEPA/SWIFT overview route with safe overview")
                logger.info("Answer strategy: sepa_swift_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "sepa_swift_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "sepa_swift_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "product_overview" in query_profile.labels and "supported_domain" in query_profile.labels and len(source_docs) == 0:
            # Generic template only when retrieval is nearly empty — with real docs
            # let LLM synthesize from context instead of serving a generic product list.
            overview_answer = _format_product_overview_answer(source_docs, query_labels=query_profile.labels)
            if overview_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", "supported product overview generic route with safe overview")
                logger.info("Answer strategy: product_overview_direct (LLM skipped)")
                return {
                    "answer": overview_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "product_overview_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "product_overview_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        if "credit_card_catalog" in query_profile.labels:
            catalog_answer = _format_credit_card_catalog_answer(source_docs)
            if catalog_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                logger.info("Answer strategy: credit_card_catalog_direct (LLM skipped)")
                ux = _ux_meta("high", "deterministic product catalog answer from credit-card sources")
                return {
                    "answer": catalog_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "credit_card_catalog_direct",
                    "answer_confidence": "high",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "credit_card_catalog_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }
        # Priority 2: Soft guidance route — if the query matches a known
        # FAQ/low-risk pattern, use a safe deterministic answer instead of
        # relying on weak retrieval + LLM generation.
        # Use original `question`, not `retrieval_query` — see note above.
        soft_intent = _soft_guidance_intent(question)
        if soft_intent and "pricing" not in query_profile.labels:
            soft_answer = _soft_guidance_answer(soft_intent)
            if soft_answer:
                total_ms = (time.perf_counter() - t_ask) * 1000
                ux = _ux_meta("medium", f"soft guidance for {soft_intent} (weak retrieval)", confidence_factors={"authority_boost_used": True, "soft_guidance_used": True, "retrieval_weak": True, "source_count": len(source_docs)})
                logger.info(f"Answer strategy: soft_guidance_direct ({soft_intent}, weak retrieval)")
                if self.conversational:
                    self.chat_history.append(HumanMessage(content=question))
                    self.chat_history.append(AIMessage(content=soft_answer))
                    limit = config.CONVERSATION_HISTORY_LIMIT
                    if len(self.chat_history) > limit * 2:
                        self.chat_history = self.chat_history[-(limit * 2):]
                return {
                    "answer": soft_answer,
                    "sources": source_docs,
                    "rewritten_query": retrieval_query,
                    "answer_strategy": "soft_guidance_direct",
                    "answer_confidence": "medium",
                    "retrieval_debug": _debug_with_ux(self._retrieval_debug(source_docs, "soft_guidance_direct"), ux),
                    **ux,
                    "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
                }

        answer_strategy = "generic_llm"
        answer_confidence = "medium"
        if top_doc in structured_docs:
            answer_strategy = "pricing_row_direct"
            answer_confidence = "high"
        elif "pricing" in query_profile.labels and top_doc.metadata.get("chunk_type") in {"table", "pdf_table"} and top_doc.metadata.get("document_type") == "pricing":
            answer_strategy = "pricing_table_llm"
        elif "pricing" in query_profile.labels and top_doc.metadata.get("document_type") == "pricing":
            answer_strategy = "pricing_section_llm"

        # --- Graceful degradation P1: pricing → overview fallback ---
        # If pricing retrieval only returned warning docs (no real data) AND
        # we can identify a supported product → serve overview fallback instead
        # of dead-end warning or hallucinated pricing.
        if answer_strategy in ("pricing_section_llm", "pricing_table_llm", "generic_llm"):
            if not _has_real_pricing_docs(source_docs, structured_docs):
                product_id = _detect_product_for_degradation(source_docs, query_profile, session_debug)
                if product_id:
                    overview_resp = _build_overview_fallback_response(
                        product_id, question, source_docs,
                        retrieval_query, retrieval_ms, t_ask,
                    )
                    if overview_resp.get("answer"):
                        if self.conversational:
                            self.chat_history.append(HumanMessage(content=question))
                            self.chat_history.append(AIMessage(content=overview_resp["answer"]))
                            limit = config.CONVERSATION_HISTORY_LIMIT
                            if len(self.chat_history) > limit * 2:
                                self.chat_history = self.chat_history[-(limit * 2):]
                        logger.info(
                            f"Graceful degradation: pricing → overview_fallback "
                            f"(product={product_id}, no real pricing data)"
                        )
                        return overview_resp

        if answer_strategy == "pricing_row_direct" and structured_docs:
            answer_text = format_structured_pricing_answer(structured_docs, max_products=3)
            total_ms = (time.perf_counter() - t_ask) * 1000
            if self.conversational:
                self.chat_history.append(HumanMessage(content=question))
                self.chat_history.append(AIMessage(content=answer_text))
                limit = config.CONVERSATION_HISTORY_LIMIT
                if len(self.chat_history) > limit * 2:
                    self.chat_history = self.chat_history[-(limit * 2):]
            logger.info("Answer strategy: pricing_row_direct (LLM skipped)")
            ux = _ux_meta("high", "validated structured pricing row")
            return {
                "answer": answer_text,
                "sources": _minimal_structured_sources(structured_docs),
                "rewritten_query": retrieval_query,
                "answer_strategy": answer_strategy,
                "answer_confidence": answer_confidence,
                "retrieval_debug": _debug_with_ux(self._structured_retrieval_debug(structured_docs, answer_strategy), ux),
                **ux,
                "timing_ms": {"retrieval": round(retrieval_ms), "total": round(total_ms), "llm": 0},
            }

        # 3. Formátování kontextu
        context = format_context(source_docs)

        # 4. Generování odpovědi
        if self.conversational and self.chat_history:
            messages = get_conversational_prompt().format_messages(
                context=context,
                chat_history=self.chat_history,
                question=question,
            )
        else:
            messages = get_simple_prompt().format_messages(
                context=context,
                question=question,
            )

        backend = config.LLM_BACKEND
        model_name = {
            "anthropic": config.ANTHROPIC_MODEL,
            "gemini": config.GEMINI_MODEL,
            "openai": config.OPENAI_CHAT_MODEL,
        }.get(backend, config.LLM_MODEL)
        answer_text, llm_ms, answer_strategy, answer_confidence = self._invoke_llm(
            messages, source_docs, answer_strategy, answer_confidence, question,
            retrieval_ms, retrieval_query, query_profile, session_debug, t_ask,
        )

        confidence_bucket_value = answer_confidence if answer_confidence in {"high", "medium", "low"} else "medium"
        confidence_reason = "structured pricing/source-backed answer" if answer_strategy.startswith("pricing_") else "source-backed generated answer"
        if any(marker in answer_text.lower() for marker in NO_ANSWER_MARKERS):
            # P1/P4: Before falling back to unsupported, try graceful degradation
            # for non-pricing flows where LLM couldn't answer.
            product_id = _detect_product_for_degradation(source_docs, query_profile, session_debug)
            degraded_used_product = product_id
            if product_id and not answer_strategy.startswith("pricing_"):
                overview_resp = _build_overview_fallback_response(
                    product_id, question, source_docs,
                    retrieval_query, retrieval_ms, t_ask,
                )
                if overview_resp.get("answer"):
                    if self.conversational:
                        self.chat_history.append(HumanMessage(content=question))
                        self.chat_history.append(AIMessage(content=overview_resp["answer"]))
                        limit = config.CONVERSATION_HISTORY_LIMIT
                        if len(self.chat_history) > limit * 2:
                            self.chat_history = self.chat_history[-(limit * 2):]
                    logger.info(
                        f"Graceful degradation post-LLM: {answer_strategy} → overview_fallback "
                        f"(product={product_id})"
                    )
                    return overview_resp

            confidence_bucket_value = "low"
            confidence_reason = "model indicated insufficient support"
            # P4: Replace dead-end unsupported with enriched CTA
            answer_text = _enrich_dead_end_answer(UNSUPPORTED_RESPONSE, degraded_used_product)
        ux = _ux_meta(confidence_bucket_value, confidence_reason)

        # P2: Resolve confidence semantics
        cs = resolve_confidence_semantics(answer_strategy, bucket=confidence_bucket_value, reason=confidence_reason)

        total_ms = (time.perf_counter() - t_ask) * 1000

        # 5. Aktualizace konverzační historie
        if self.conversational:
            self.chat_history.append(HumanMessage(content=question))
            self.chat_history.append(AIMessage(content=answer_text))
            limit = config.CONVERSATION_HISTORY_LIMIT
            if len(self.chat_history) > limit * 2:
                self.chat_history = self.chat_history[-(limit * 2):]

        logger.info(
            f"⏱ LLM generation ({backend}/{model_name}): {llm_ms:.0f}ms "
            f"({len(answer_text)} znaků)"
        )
        logger.info(
            f"⏱ TOTAL ask(): {total_ms:.0f}ms "
            f"[retrieval={retrieval_ms:.0f}ms, llm={llm_ms:.0f}ms]"
        )
        return {
            "answer": answer_text,
            "sources": _minimal_structured_sources(_structured_pricing_docs(source_docs)) if answer_strategy == "pricing_row_direct" else source_docs,
            "rewritten_query": retrieval_query,
            "answer_strategy": answer_strategy,
            "answer_confidence": answer_confidence,
            "confidence_origin": cs.origin,
            "confidence_origin_label": cs.origin_label,
            "confidence_semantic_label": cs.semantic_label,
            "degraded_answer": cs.degraded,
            "retrieval_debug": _debug_with_ux(
                self._structured_retrieval_debug(_structured_pricing_docs(source_docs), answer_strategy) if answer_strategy == "pricing_row_direct" else self._retrieval_debug(source_docs, answer_strategy),
                ux,
            ),
            **ux,
        }

    # ------------------------------------------------------------------
    # True token streaming (Priority 1)
    # ------------------------------------------------------------------

    def _invoke_llm(
        self,
        messages: list[BaseMessage],
        source_docs: list[Document],
        answer_strategy: str,
        answer_confidence: str,
        question: str,
        retrieval_ms: float,
        retrieval_query: str,
        query_profile: object,
        session_debug: dict,
        t_ask: float,
    ) -> tuple[str, float, str, str]:
        """Invoke the LLM synchronously and apply post-processing.

        Returns (answer_text, llm_ms, answer_strategy, answer_confidence).
        Also handles pricing fallback and no-answer markers.
        """
        t_llm = time.perf_counter()
        # Select appropriate LLM based on answer_strategy
        if answer_strategy.startswith("overview_") or answer_strategy.startswith("comparison_") or answer_strategy.startswith("advisory_") or answer_strategy == "generic_llm":
            llm = self._llm
        elif answer_strategy.startswith("procedural_flow") or answer_strategy.startswith("clarification"):
            llm = self._fast_llm
        else:
            llm = self._llm
        answer = llm.invoke(messages)
        llm_ms = (time.perf_counter() - t_llm) * 1000
        answer_text = answer if isinstance(answer, str) else str(answer)
        answer_text = _normalize_answer_text(answer_text, answer_strategy=answer_strategy)
        if answer_strategy.startswith("pricing_") and any(marker in answer_text.lower() for marker in NO_ANSWER_MARKERS):
            structured_fallback_docs = _structured_pricing_docs(source_docs)
            if structured_fallback_docs:
                answer_text = format_structured_pricing_answer(structured_fallback_docs, max_products=3)
                answer_strategy = "pricing_row_direct"
                answer_confidence = "high"
                logger.warning("LLM vrátil fallback apology navzdory pricing_row; použita strukturovaná odpověď")
        return answer_text, llm_ms, answer_strategy, answer_confidence

    def ask_stream(self, question: str) -> Generator[dict, None, None]:
        """Process a question with true token streaming from the LLM.

        Yields dict events:
          {"type": "start", "answer_strategy": ..., "sources": [...], "confidence_bucket": ..., ...}
          {"type": "token", "text": "..."}  — one per LLM token / full deterministic answer
          {"type": "done", "processing_time_ms": ..., "retrieval_latency_ms": ..., ...}
          {"type": "error", "error": "...", "detail": "..."}

        Deterministic routes yield the full answer as a single token.
        LLM routes yield tokens incrementally as they arrive.
        """
        import json
        import threading

        # We use a thread-safe buffer to receive tokens from the streaming
        # LLM wrapper while ask() runs in a background thread.
        token_buffer: list[str] = []
        start_event_data: dict = {}
        result_container: list[dict | None] = [None]
        error_container: list[Exception | None] = [None]
        llm_started = threading.Event()

        class _StreamingInvoker:
            """Wraps self._llm to intercept invoke() and stream tokens."""

            def __init__(self, real_llm, buffer, started_event):
                self._real_llm = real_llm
                self._buffer = buffer
                self._started = started_event
                self._has_stream = hasattr(real_llm, "stream") and callable(
                    getattr(real_llm, "stream", None)
                )

            def invoke(self, msgs):
                """Replacement for LLM.invoke(). Collects tokens into buffer."""
                self._started.set()
                if self._has_stream:
                    full = ""
                    for token in self._real_llm.stream(msgs):
                        full += token
                        self._buffer.append(token)
                    return full
                # Fallback for backends without stream() — yield full answer as one token
                full = self._real_llm.invoke(msgs)
                self._buffer.append(full)
                return full

        original_llm = self._llm
        streaming_llm = _StreamingInvoker(original_llm, token_buffer, llm_started)
        self._llm = streaming_llm  # type: ignore[assignment]

        t_start = time.perf_counter()

        def _run_ask():
            try:
                result = BankingRAGChain.ask(self, question)
                result_container[0] = result
            except Exception as exc:
                error_container[0] = exc
            finally:
                # Unblock llm_started.wait() for deterministic routes that skip LLM
                llm_started.set()

        thread = threading.Thread(target=_run_ask, daemon=True)
        thread.start()

        # Wait until either:
        # 1. The LLM streaming starts (routing complete, LLM generating)
        # 2. Or ask() finishes entirely (deterministic route)
        # Timeout prevents hanging if something goes wrong.
        llm_started.wait(timeout=config.LLM_TIMEOUT)
        elapsed_until_llm = (time.perf_counter() - t_start) * 1000
        logger.debug(
            f"ask_stream llm_started fired: elapsed={elapsed_until_llm:.0f}ms "
            f"buffer_size={len(token_buffer)} thread_alive={thread.is_alive()}"
        )

        if error_container[0]:
            self._llm = original_llm
            yield {"type": "error", "error": "chain_error", "detail": str(error_container[0])}
            return

        # If ask() already completed, it was a deterministic route
        thread.join(timeout=0.1)
        logger.debug(
            f"ask_stream join(0.1): thread_alive={thread.is_alive()} "
            f"result_ready={result_container[0] is not None} "
            f"buffer_size={len(token_buffer)}"
        )
        if result_container[0] is not None:
            self._llm = original_llm
            result = result_container[0]
            # Save for downstream caching
            self._last_stream_result = result  # type: ignore[attr-defined]
            yield {
                "type": "start",
                "answer_strategy": result.get("answer_strategy"),
                "sources": result.get("sources", []),
                "confidence_bucket": result.get("confidence_bucket"),
                "confidence_reason": result.get("confidence_reason"),
                "confidence_semantic_label": result.get("confidence_semantic_label"),
                "confidence_origin": result.get("confidence_origin"),
                "degraded_answer": result.get("degraded_answer"),
                "clarification_required": result.get("clarification_required"),
                "unsupported_reason": result.get("unsupported_reason"),
                "cache_hit": False,
            }
            yield {"type": "token", "text": result.get("answer", "")}
            yield {"type": "done", "processing_time_ms": round(elapsed_until_llm, 1)}
            return

        # LLM route: wait for tokens to arrive
        yield {
            "type": "start",
            "answer_strategy": "generic_llm",
            "cache_hit": False,
            "clarification_required": False,
            "unsupported_reason": None,
        }

        # Stream tokens as they arrive
        last_token_count = 0
        while thread.is_alive() or len(token_buffer) > last_token_count:
            if len(token_buffer) > last_token_count:
                new_tokens = token_buffer[last_token_count:]
                for token in new_tokens:
                    yield {"type": "token", "text": token}
                last_token_count = len(token_buffer)
            else:
                # Yield control to event loop briefly
                threading.Event().wait(0.01)

        # Flush any remaining tokens
        if len(token_buffer) > last_token_count:
            for token in token_buffer[last_token_count:]:
                yield {"type": "token", "text": token}

        # Restore original LLM
        self._llm = original_llm

        # Get the final result dict
        if error_container[0]:
            yield {"type": "error", "error": "chain_error", "detail": str(error_container[0])}
            return

        result = result_container[0]
        if result is None:
            self._llm = original_llm
            yield {"type": "error", "error": "no_result", "detail": "ask() returned None"}
            return

        # Save for downstream caching (SSE endpoint reads this after generator completes)
        self._last_stream_result = result  # type: ignore[attr-defined]

        answer_strategy = result.get("answer_strategy", "")

        # Safety net: if no tokens were streamed (buffer empty), the answer was never
        # sent. This covers ALL direct strategies (soft_guidance_direct, guided_flow_direct,
        # supported_but_missing_data_fallback, unsupported_domain_fallback, etc.) that
        # fell into the LLM streaming path due to thread.join() timing or early
        # llm_started firing (e.g. from a conversational query-rewrite LLM call).
        if not token_buffer:
            answer_text = result.get("answer", "")
            if answer_text:
                logger.debug(
                    f"ask_stream safety-net: sending answer as single token "
                    f"(strategy={answer_strategy}, buffer_empty=True, len={len(answer_text)})"
                )
                yield {"type": "token", "text": answer_text}

        timing = result.get("timing_ms", {}) or {}
        elapsed_total = (time.perf_counter() - t_start) * 1000
        logger.debug(
            f"ask_stream done: strategy={answer_strategy} "
            f"buffer_tokens={len(token_buffer)} elapsed={elapsed_total:.0f}ms"
        )
        yield {
            "type": "done",
            "processing_time_ms": round(elapsed_total, 1),
            "retrieval_latency_ms": timing.get("retrieval"),
            "llm_latency_ms": timing.get("llm"),
            "formatting_latency_ms": timing.get("formatting_latency_ms"),
            "answer_strategy": answer_strategy,
            "sources": result.get("sources", []),
            "confidence_bucket": result.get("confidence_bucket"),
            "confidence_semantic_label": result.get("confidence_semantic_label"),
            "confidence_origin": result.get("confidence_origin"),
            "degraded_answer": result.get("degraded_answer"),
        }

    # ------------------------------------------------------------------
    # Priority 4: Session context helpers
    # ------------------------------------------------------------------

    def _update_session_context(
        self,
        query_profile: QueryProfile | None = None,
        *,
        raw_question: str | None = None,
    ) -> None:
        """Update session_context from query profile or raw question.

        Detects domain, intent, and product from the current query and
        stores them for follow-up inheritance.

        Safe to call even if session_context hasn't been initialized
        (e.g. tests using __new__ without __init__).
        """
        if not hasattr(self, "session_context") or self.session_context is None:
            return
        if query_profile is not None:
            labels = query_profile.labels

            # Domain detection
            if "retail_banking" in labels:
                self.session_context["current_domain"] = "retail"
            elif "corporate_banking" in labels:
                self.session_context["current_domain"] = "corporate"
            else:
                self.session_context["current_domain"] = self.session_context.get("current_domain")

            # Intent detection (first matched overview/intent label)
            intent_order = [
                "card_overview", "account_overview", "mortgage_overview",
                "investment_overview", "rb_key_overview", "payment_overview",
                "sepa_swift_overview", "product_overview", "pricing",
                "credit_card_catalog", "credit_card", "faq",
            ]
            for intent in intent_order:
                if intent in labels:
                    self.session_context["current_intent"] = intent
                    break

        # Product from chain attributes
        if self.resolved_product:
            self.session_context["resolved_product"] = self.resolved_product
        if self.resolved_intent:
            self.session_context["current_intent"] = self.resolved_intent

    def _get_session_debug(self, inherited_product: str | None, inherited_intent: str | None) -> dict:
        """Build session context debug fields for the API response."""
        debug: dict[str, Any] = {}
        if inherited_product or inherited_intent:
            debug["session_context_used"] = True
        if inherited_product:
            debug["inherited_product"] = inherited_product
        if inherited_intent:
            debug["inherited_intent"] = inherited_intent
        return debug

    def _check_session_inheritance(self, question: str) -> tuple[str | None, str | None]:
        """Check if the current question should inherit context from previous turn.

        Returns (inherited_product, inherited_intent) if inheritance is needed,
        or (None, None) if the question is self-contained.
        """
        # Guard against uninitialized session_context
        if not hasattr(self, "session_context") or not self.session_context:
            return None, None
        # If the question is very short (1-3 words) and we have previous context,
        # it's likely a follow-up
        word_count = len(question.strip().split())
        if word_count <= 4 and self.chat_history:
            inherited_product = self.session_context.get("resolved_product") or self.session_context.get("current_product")
            inherited_intent = self.session_context.get("current_intent")
            if inherited_product or inherited_intent:
                return inherited_product, inherited_intent
        return None, None

    def _retrieval_debug(self, source_docs: list[Document], answer_strategy: str) -> list[dict]:
        return [
            {
                "title": doc.metadata.get("title"),
                "source_url": doc.metadata.get("source_url") or doc.metadata.get("url"),
                "chunk_type": doc.metadata.get("chunk_type"),
                "document_type": doc.metadata.get("document_type"),
                "category": doc.metadata.get("category"),
                "product_name": doc.metadata.get("product_name"),
                "fee_type": doc.metadata.get("fee_type"),
                "fee_value": doc.metadata.get("fee_value"),
                "pricing_canonical_source": doc.metadata.get("pricing_canonical_source"),
                "extracted_pricing_row": doc.metadata.get("extracted_pricing_row"),
                "normalized_price": doc.metadata.get("normalized_price"),
                "normalized_currency": doc.metadata.get("normalized_currency"),
                "normalized_billing_period": doc.metadata.get("normalized_billing_period"),
                "pricing_semantic_label": doc.metadata.get("pricing_semantic_label"),
                "conditional_pricing_detected": doc.metadata.get("conditional_pricing_detected"),
                "condition_type": doc.metadata.get("condition_type"),
                "condition_text": doc.metadata.get("condition_text"),
                "base_price": doc.metadata.get("base_price"),
                "conditional_price": doc.metadata.get("conditional_price"),
                "pricing_logic": doc.metadata.get("pricing_logic"),
                "pricing_confidence": doc.metadata.get("pricing_confidence"),
                "pricing_source_type": doc.metadata.get("pricing_source_type"),
                "pricing_row_found": doc.metadata.get("pricing_row_found"),
                "pricing_row_exact_match": doc.metadata.get("pricing_row_exact_match"),
                "pricing_canonical_used": doc.metadata.get("pricing_canonical_used"),
                "pricing_canonical_override": doc.metadata.get("pricing_canonical_override"),
                "pricing_resolver_used": doc.metadata.get("pricing_resolver_used"),
                "chunk_quality": doc.metadata.get("chunk_quality"),
                "hybrid_score": doc.metadata.get("hybrid_score"),
                "hybrid_base_score": doc.metadata.get("hybrid_base_score"),
                "metadata_boost": doc.metadata.get("metadata_boost"),
                "freshness_score": doc.metadata.get("freshness_score"),
                "archived_penalty": doc.metadata.get("archived_penalty"),
                "document_year": doc.metadata.get("document_year"),
                "document_date": doc.metadata.get("document_date"),
                "is_archived": doc.metadata.get("is_archived"),
                "is_discontinued": doc.metadata.get("is_discontinued"),
                "rerank_score": doc.metadata.get("rerank_score"),
                "reasons": doc.metadata.get("retrieval_reasons"),
                "query_labels": doc.metadata.get("query_labels"),
                "rewritten_query": doc.metadata.get("rewritten_query"),
                "retrieval_route": doc.metadata.get("retrieval_route"),
                "fallback_used": doc.metadata.get("fallback_used"),
                "fallback_retrieval_used": doc.metadata.get("fallback_retrieval_used"),
                "expanded_query": doc.metadata.get("expanded_query"),
                "fallback_source_count": doc.metadata.get("fallback_source_count"),
                "catalog_intent_detected": doc.metadata.get("catalog_intent_detected"),
                "boosted_product_group": doc.metadata.get("boosted_product_group"),
                "expanded_credit_card_terms": doc.metadata.get("expanded_credit_card_terms"),
                "matched_credit_card_sources": doc.metadata.get("matched_credit_card_sources"),
                "overview_route_used": doc.metadata.get("overview_route_used"),
                "overview_type": doc.metadata.get("overview_type"),
                "supported_domain_detected": doc.metadata.get("supported_domain_detected"),
                "unsupported_guard_bypassed": doc.metadata.get("unsupported_guard_bypassed"),
                "fallback_card_retrieval_used": doc.metadata.get("fallback_card_retrieval_used"),
                "fallback_overview_retrieval_used": doc.metadata.get("fallback_overview_retrieval_used"),
                "metadata_boost_reason": doc.metadata.get("metadata_boost_reason"),
                "faq_priority_used": doc.metadata.get("faq_priority_used"),
                # Priority 1: Authority scoring fields
                "authority_score": doc.metadata.get("authority_score"),
                "authority_tier": doc.metadata.get("authority_tier"),
                # Source governance fields (P1–P3)
                "suppression_applied": doc.metadata.get("suppression_applied"),
                "suppression_reason": doc.metadata.get("suppression_reason"),
                "canonical_priority": doc.metadata.get("canonical_priority"),
                "canonical_source_type": doc.metadata.get("canonical_source_type"),
                "canonical_override_used": doc.metadata.get("canonical_override_used"),
                "lineage_superseded": doc.metadata.get("lineage_superseded"),
                # Retrieval Recovery & Resilience fields
                "governance_removed_count": doc.metadata.get("governance_removed_count"),
                "governance_suppressed_count": doc.metadata.get("governance_suppressed_count"),
                "suppression_ratio": doc.metadata.get("suppression_ratio"),
                "recovery_pass_used": doc.metadata.get("recovery_pass_used"),
                "recovery_applied": doc.metadata.get("recovery_applied"),
                "recovery_reason": doc.metadata.get("recovery_reason"),
                "recovery_query": doc.metadata.get("recovery_query"),
                "recovery_result_count": doc.metadata.get("recovery_result_count"),
                "recovery_pass_latency_ms": doc.metadata.get("recovery_pass_latency_ms"),
                "retrieval_collapse_detected": doc.metadata.get("retrieval_collapse_detected"),
                "resilience_strategy": doc.metadata.get("resilience_strategy"),
                "resilience_category": doc.metadata.get("resilience_category"),
                "resilience_category_derived": doc.metadata.get("resilience_category_derived"),
                "resilience_category_source": doc.metadata.get("resilience_category_source"),
                "final_source_count": doc.metadata.get("final_source_count"),
                "diversity_document_key": doc.metadata.get("diversity_document_key"),
                "diversity_family_key": doc.metadata.get("diversity_family_key"),
                "source_diversity_score": doc.metadata.get("source_diversity_score"),
                "diversity_score": doc.metadata.get("diversity_score"),
                "diversity_override_used": doc.metadata.get("diversity_override_used"),
                "max_chunks_per_document": doc.metadata.get("max_chunks_per_document"),
                "max_chunks_per_family": doc.metadata.get("max_chunks_per_family"),
                "empty_category_count": doc.metadata.get("empty_category_count"),
                "derived_category_count": doc.metadata.get("derived_category_count"),
                # Priority 4: Confidence factors
                "authority_boost_used": doc.metadata.get("authority_boost_used"),
                "stale_penalty_used": doc.metadata.get("stale_penalty_used"),
                "retrieval_soft_fail": doc.metadata.get("retrieval_soft_fail"),
                "answer_strategy": answer_strategy,
            }
            for doc in source_docs
        ]

    def _structured_retrieval_debug(self, source_docs: list[Document], answer_strategy: str) -> list[dict]:
        return [
            {
                "answer_strategy": answer_strategy,
                "product_name": doc.metadata.get("product_name"),
                "fee_type": doc.metadata.get("fee_type"),
                "fee_value": doc.metadata.get("fee_value"),
                "pricing_canonical_source": doc.metadata.get("pricing_canonical_source"),
                "extracted_pricing_row": doc.metadata.get("extracted_pricing_row"),
                "normalized_price": doc.metadata.get("normalized_price"),
                "normalized_currency": doc.metadata.get("normalized_currency"),
                "normalized_billing_period": doc.metadata.get("normalized_billing_period"),
                "pricing_semantic_label": doc.metadata.get("pricing_semantic_label"),
                "conditional_pricing_detected": doc.metadata.get("conditional_pricing_detected"),
                "condition_type": doc.metadata.get("condition_type"),
                "condition_text": doc.metadata.get("condition_text"),
                "base_price": doc.metadata.get("base_price"),
                "conditional_price": doc.metadata.get("conditional_price"),
                "pricing_logic": doc.metadata.get("pricing_logic"),
                "pricing_confidence": doc.metadata.get("pricing_confidence"),
                "pricing_source_type": doc.metadata.get("pricing_source_type"),
                "pricing_row_found": doc.metadata.get("pricing_row_found"),
                "pricing_row_exact_match": doc.metadata.get("pricing_row_exact_match"),
                "pricing_canonical_used": doc.metadata.get("pricing_canonical_used"),
                "confidence": doc.metadata.get("confidence"),
                "source": doc.metadata.get("source_file") or doc.metadata.get("title"),
                "page": doc.metadata.get("page"),
                "recovery_pass_used": doc.metadata.get("recovery_pass_used"),
                "recovery_reason": doc.metadata.get("recovery_reason"),
                "governance_suppressed_count": doc.metadata.get("governance_suppressed_count"),
                "diversity_score": doc.metadata.get("diversity_score"),
                "retrieval_collapse_detected": doc.metadata.get("retrieval_collapse_detected"),
                "resilience_strategy": doc.metadata.get("resilience_strategy"),
            }
            for doc in source_docs[:3]
        ]

    def reset_history(self) -> None:
        """Vymaže konverzační historii (nové sezení)."""
        self.chat_history = []
        logger.info("Konverzační historie vymazána")

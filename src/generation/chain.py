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
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import OllamaLLM

import config
from src.generation.prompts import (
    CONVERSATIONAL_PROMPT,
    QUERY_REWRITE_PROMPT,
    SIMPLE_PROMPT,
    format_context,
)
from src.retrieval.retriever import BankingRetriever
from src.retrieval.query_classifier import classify_query
from src.utils.logger import get_logger

logger = get_logger(__name__)

NO_ANSWER_MARKERS = (
    "nenalezl jsem",
    "nenašel jsem",
    "kontaktujte zákaznickou linku",
    "kontaktujte podporu",
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

EKONTO_CLARIFICATION = (
    "Upřesněte prosím, zda myslíte osobní eKonto, nebo podnikatelské eKonto. "
    "Stačí odpovědět například „osobní“ nebo „podnikatelské“."
)

GUIDED_FLOW_PATTERNS = (
    (re.compile(r"(ztratil|ztratila|ztrata|ztráta|ukrad|odcizen).*(kart\w*)|blokac(e|i|e)\s+kart\w*", re.I), "card_blocking"),
    (re.compile(r"(co\s+m[aá]m\s+d[eě]lat|neoprávněn|neopravnen|podezřel).*(platb|transakc|karta)", re.I), "complaint"),
    (re.compile(r"(jak\s+zadat|údaje|udaje|iban|bic).*(sepa|swift|zahraničn|zahranicn)", re.I), "sepa_swift"),
    (re.compile(r"(rb\s+klíč|rb\s+klic).*(aktiv|nefung|odblok|přen|pren|telefon|mobil)", re.I), "rb_key"),
    (re.compile(r"(jak\s+požádat|jak\s+pozadat|chci|vyřídit|vyridit).*(hypot[eé]k)", re.I), "mortgage"),
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
    }]


def _ux_meta(bucket: str, reason: str, *, clarification_required: bool = False, unsupported_reason: str | None = None) -> dict:
    return {
        "confidence_bucket": bucket,
        "confidence_reason": reason,
        "clarification_required": clarification_required,
        "unsupported_reason": unsupported_reason,
    }


def _debug_with_ux(rows: list[dict], ux: dict) -> list[dict]:
    if not rows:
        return [ux]
    return [{**row, **ux} for row in rows]


def _is_ekonto_ambiguous_pricing(question: str) -> bool:
    q = (question or "").lower()
    return "ekonto" in q and any(k in q for k in ("kolik", "stoj", "poplatek", "vedení", "vedeni")) and not any(
        k in q for k in ("osobní", "osobni", "podnikat", "firem", "firma", "osvč", "osvc")
    )


def _resolve_pending_clarification(question: str, context: dict | None) -> tuple[str, str, str] | None:
    if not context or context.get("type") != "ekonto_pricing":
        return None
    q = (question or "").lower().strip()
    if any(k in q for k in ("osob", "soukrom", "retail")):
        return "Kolik stojí vedení osobního eKonta?", "osobní eKonto", "pricing"
    if any(k in q for k in ("podnik", "osvč", "osvc", "firma", "firem")):
        return "Kolik stojí vedení podnikatelského eKonta?", "podnikatelské eKonto", "pricing"
    return None


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


def _guided_flow_answer(intent: str) -> str:
    flows = {
        "card_blocking": (
            "Doporučený postup při ztrátě nebo podezření na zneužití karty:\n"
            "1. Kartu ihned zablokujte v mobilním/internetovém bankovnictví, pokud ho máte k dispozici.\n"
            "2. Pokud se do bankovnictví nedostanete, kontaktujte nonstop podporu Raiffeisenbank.\n"
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
    }
    return flows[intent]


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
    """Extract a conservative credit-card product list from retrieved catalog chunks."""
    candidates = [
        "Kreditní karta EASY",
        "Kreditní karta STYLE",
        "Kreditní karta RB PREMIUM",
        "Kreditní karta Visa Gold",
        "Kreditní karta O2 RB",
        "Partnerská kreditní karta O2 RB Club",
    ]
    hay = "\n".join(
        " ".join([
            str(doc.metadata.get("title") or doc.metadata.get("file_name") or ""),
            str(doc.metadata.get("source_url") or doc.metadata.get("url") or ""),
            doc.page_content[:5000],
        ])
        for doc in docs
    ).lower()
    products = [name for name in candidates if name.lower() in hay]
    if not products and any(term in hay for term in ("kreditní karty raiffeisenbank", "kreditni-karty", "kreditní karta")):
        products = ["Kreditní karty Raiffeisenbank"]
    return list(dict.fromkeys(products))[:5]


def _format_credit_card_catalog_answer(docs: list[Document]) -> str | None:
    products = _credit_card_products_from_docs(docs)
    if not products:
        return None
    lines = ["Raiffeisenbank v dostupných zdrojích uvádí tyto kreditní karty / kreditní produkty:", ""]
    for product in products:
        if "easy" in product.lower():
            desc = "základní kreditní karta zaměřená na jednoduché používání."
        elif "style" in product.lower():
            desc = "kreditní karta s odměnami / výhodami."
        elif "premium" in product.lower():
            desc = "prémiovější kreditní karta."
        elif "visa gold" in product.lower():
            desc = "kreditní karta typu Visa Gold."
        elif "o2" in product.lower():
            desc = "partnerská kreditní karta O2 RB Club."
        else:
            desc = "katalog kreditních karet Raiffeisenbank."
        lines.append(f"- {product}: {desc}")
    lines.extend([
        "",
        "Pro výběr konkrétní karty doporučuji otevřít detail produktu a porovnat podmínky, limity, bonusy a poplatky.",
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


def _format_product_overview_answer(docs: list[Document]) -> str | None:
    """Safe generic formatter for any supported product overview as fallback."""
    if docs:
        first = docs[0]
        source = first.metadata.get("source_url") or first.metadata.get("url") or first.metadata.get("file_name") or "rb.cz"
    else:
        source = "rb.cz"

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


# ---------------------------------------------------------------------------
# Factory – výběr backendu dle konfigurace
# ---------------------------------------------------------------------------

def _build_llm() -> OllamaLLM | AnthropicLLM:
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
        return OpenAILLM(
            model=config.OPENAI_CHAT_MODEL,
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

        self._llm = _build_llm()
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

        messages = QUERY_REWRITE_PROMPT.format_messages(
            chat_history=self.chat_history,
            question=question,
        )
        rewritten = self._llm.invoke(messages)
        # OllamaLLM vrátí str, AnthropicLLM také vrátí str
        rewritten_text = rewritten if isinstance(rewritten, str) else str(rewritten)
        logger.debug(f"Query rewrite: '{question}' → '{rewritten_text.strip()}'")
        return rewritten_text.strip()

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

        # 0. System/orchestration intents are evaluated on the raw user turn so
        # conversational query rewriting cannot contaminate assistant identity or
        # urgent guided flows with previous banking context.
        raw_resolved = _resolve_pending_clarification(question, getattr(self, "clarification_context", None))
        if raw_resolved:
            retrieval_query, self.resolved_product, self.resolved_intent = raw_resolved
            self.pending_clarification = None
            self.clarification_context = None
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

        # 1. Query rewriting pro follow-up otázky
        t_rewrite = time.perf_counter()
        if not retrieval_query:
            retrieval_query = (
                self._rewrite_query(question)
                if self.conversational
                else question
            )
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
                }], ux),
                "answer_strategy": "clarification_direct",
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

        # 2. Retrieval
        t_retrieval = time.perf_counter()
        source_docs: list[Document] = self._retriever.invoke(retrieval_query)
        retrieval_ms = (time.perf_counter() - t_retrieval) * 1000

        if not source_docs:
            overview_profile = classify_query(retrieval_query)
            if "product_overview" in overview_profile.labels and "supported_domain" in overview_profile.labels:
                # Supported overview query with empty retrieval — still provide a safe overview.
                overview_answer = _format_product_overview_answer([])
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
            answer = UNSUPPORTED_RESPONSE
            ux = _ux_meta("low", "retrieval returned no source documents", unsupported_reason="no_retrieval_sources")
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
                "retrieval_debug": _debug_with_ux([{"retrieval_route": "unsupported", "retrieval_skipped": False}], ux),
                "answer_strategy": "fallback_no_answer",
                "answer_confidence": "low",
                **ux,
            }

        top_doc = source_docs[0]
        structured_docs = _structured_pricing_docs(source_docs)
        query_profile = classify_query(retrieval_query)
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
        if "account_overview" in query_profile.labels:
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
        if "product_overview" in query_profile.labels and "supported_domain" in query_profile.labels:
            # Generic fallback for any supported product overview not handled above.
            overview_answer = _format_product_overview_answer(source_docs)
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
        answer_strategy = "generic_llm"
        answer_confidence = "medium"
        if top_doc in structured_docs:
            answer_strategy = "pricing_row_direct"
            answer_confidence = "high"
        elif top_doc.metadata.get("chunk_type") in {"table", "pdf_table"} and top_doc.metadata.get("document_type") == "pricing":
            answer_strategy = "pricing_table_llm"
        elif top_doc.metadata.get("document_type") == "pricing":
            answer_strategy = "pricing_section_llm"

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
            messages = CONVERSATIONAL_PROMPT.format_messages(
                context=context,
                chat_history=self.chat_history,
                question=question,
            )
        else:
            messages = SIMPLE_PROMPT.format_messages(
                context=context,
                question=question,
            )

        backend = config.LLM_BACKEND
        model_name = {
            "anthropic": config.ANTHROPIC_MODEL,
            "gemini": config.GEMINI_MODEL,
            "openai": config.OPENAI_CHAT_MODEL,
        }.get(backend, config.LLM_MODEL)
        t_llm = time.perf_counter()
        answer = self._llm.invoke(messages)
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

        confidence_bucket_value = answer_confidence if answer_confidence in {"high", "medium", "low"} else "medium"
        confidence_reason = "structured pricing/source-backed answer" if answer_strategy.startswith("pricing_") else "source-backed generated answer"
        if any(marker in answer_text.lower() for marker in NO_ANSWER_MARKERS):
            confidence_bucket_value = "low"
            confidence_reason = "model indicated insufficient support"
            answer_text = UNSUPPORTED_RESPONSE
        ux = _ux_meta(confidence_bucket_value, confidence_reason)

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
            "retrieval_debug": _debug_with_ux(
                self._structured_retrieval_debug(_structured_pricing_docs(source_docs), answer_strategy) if answer_strategy == "pricing_row_direct" else self._retrieval_debug(source_docs, answer_strategy),
                ux,
            ),
            **ux,
        }

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
                "confidence": doc.metadata.get("confidence"),
                "source": doc.metadata.get("source_file") or doc.metadata.get("title"),
                "page": doc.metadata.get("page"),
            }
            for doc in source_docs[:3]
        ]

    def reset_history(self) -> None:
        """Vymaže konverzační historii (nové sezení)."""
        self.chat_history = []
        logger.info("Konverzační historie vymazána")

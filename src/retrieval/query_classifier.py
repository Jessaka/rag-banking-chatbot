"""Lightweight query classification and metadata-aware retrieval tuning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.documents import Document

BUSINESS_ACCOUNT_TERMS = (
    "podnikatelské", "podnikatelský", "podnikatele", "podnikatel",
    "firmy", "firma", "firemní", "firemni", "osvč", "osvc", "živnostník", "zivnostnik",
    "corp", "corporate", "fop",
)

PERSONAL_ACCOUNT_TERMS = (
    "běžný účet", "běžného účtu", "bezny ucet", "bezneho uctu",
    "osobní účet", "osobního účtu", "osobni ucet", "aktivní účet", "aktivni ucet",
    "aktivního účtu", "aktivniho uctu", "ekonto", "ekonta", "chytrý účet", "chytry ucet",
)

PERSONAL_SOURCE_TERMS = ("osobni", "osobní", "cenik-pi", "ekonto", "aktivni-ucet", "bezny-ucet")
BUSINESS_SOURCE_TERMS = ("ceniky-fop", "cenik-fop", "cenik-corp", "podnikatele", "firmy", "corp", "corporate", "fop")
ARCHIVE_QUERY_TERMS = ("starý", "stary", "historický", "historicky", "již nenabízený", "jiz nenabizeny", "již nenabízené", "jiz nenabizene", "archiv")
FAQ_TERMS = ("jak", "kde", "co dělat", "co delat", "mohu", "lze", "funguje", "nastav", "změn", "zmen", "doklad", "dokument")
COMPLAINT_TERMS = ("reklamac", "reklamovat", "neoprávněn", "neopravnen", "podezřelou transakci", "stav reklamace")
RB_KEY_TERMS = ("rb klíč", "rb klic", "klíč", "klic", "mobilní klíč", "mobilni klic")
WALLET_TERMS = ("apple pay", "google pay", "placení mobilem", "placeni mobilem", "hodinky", "wallet")
PAYMENT_RAIL_TERMS = ("sepa", "swift", "zahraniční plat", "zahranicni plat", "eur", "slovensko")
CREDIT_CARD_TERMS = (
    "kreditka", "kreditku", "kreditky", "kreditek", "kreditní karta", "kreditni karta",
    "kreditní karty", "kreditni karty", "karta na splátky", "karta na splatky",
    "splátková karta", "splatkova karta", "credit card",
)
CARD_OVERVIEW_TERMS = (
    "platební karta", "platebni karta", "platební karty", "platebni karty",
    "platebních karet", "platebnich karet", "typy karet", "druhy karet",
    "jaké karty", "jake karty", "karty nabízíte", "karty nabizite",
)
CATALOG_TERMS = (
    "jaké máte", "jake mate", "co nabízíte", "co nabizite", "nabízíte", "nabizite", "nabízí", "nabizi",
    "druhy", "typy", "jakou", "jaké jsou", "jake jsou", "můžu založit", "muzu zalozit", "založit", "zalozit",
)

ACCOUNT_OVERVIEW_TERMS = (
    "jaké účty", "jake ucty", "jaké máte účty", "jake mate ucty",
    "jaké jsou účty", "jake jsou ucty", "účty nabízíte", "ucty nabizite",
    "typy účtů", "typy uctu", "druhy účtů", "druhy uctu",
    "jaký typ účtu", "jaky typ uctu",
)
MORTGAGE_OVERVIEW_TERMS = (
    "jaké hypotéky", "jake hypoteky", "jaké máte hypotéky", "jake mate hypoteky",
    "jaké jsou hypotéky", "jake jsou hypoteky", "hypotéky nabízíte", "hypoteky nabizite",
    "typy hypoték", "typy hypotek", "druhy hypoték", "druhy hypotek",
)
INVESTMENT_OVERVIEW_TERMS = (
    "jaké investice", "jake investice", "jaké máte investice", "jake mate investice",
    "jaké jsou investice", "jake jsou investice", "investice nabízíte", "investice nabizite",
    "typy investic", "druhy investic",
)
RB_KEY_OVERVIEW_TERMS = (
    "co je rb klíč", "co je rb klic", "co je to rb klíč", "co je to rb klic",
    "co je mobilní klíč", "co je mobilni klic", "rb klíč co to je", "rb klic co to je",
    "jak funguje rb klíč", "jak funguje rb klic",
    "k čemu slouží rb klíč", "k cemu slouzi rb klic",
)
PAYMENT_OVERVIEW_TERMS = (
    "jaké typy plateb", "jake typy plateb", "jaké jsou platební metody", "jake jsou platebni metody",
    "jak platit", "typy plateb", "druhy plateb",
    "jaké platební metody", "jake platebni metody",
)
SEPA_SWIFT_OVERVIEW_TERMS = (
    "jak funguje sepa", "jak fungují sepa", "jak funguji sepa",
    "co je sepa",
    "jak funguje swift", "jak fungují swift", "jak funguji swift",
    "co je swift",
    "co je to sepa", "co je to swift",
    "jak funguje zahraniční platba", "jak fungují zahraniční platby",
    "jak funguje zahranicni platba", "jak funguji zahranicni platby",
    "sepa jak", "swift jak",
    "sepa swift", "sepa/swift",
    "sepa platba", "swift platba",
    "zahraniční platba jak", "zahranicni platba jak",
)


# --- Priority 3: Procedural flow route term tuples ---
ACTIVATION_FLOW_TERMS = (
    "aktivuj", "aktivovat", "aktivace", "zapnout", "zapni",
    "jak aktivovat", "jak aktivuju", "jak zapnout",
    "jak začít používat", "jak zacit pouzivat",
)
CARD_LIMIT_FLOW_TERMS = (
    "zvýšit limit", "zvysit limit", "zvýším limit", "zvysim limit",
    "zvýší limit", "zvysi limit", "zvýšit", "zvysit", "zvýš", "zvys",
    "navýšit limit", "navysit limit", "navýš", "navys",
    "jaký mám limit", "jaky mam limit", "zvýšení limitu", "zvyseni limitu",
    "navýšení limitu", "navyseni limitu", "limit karty",
    "snížit limit", "snizit limit", "sníž", "sniz",
)
MOBILE_WALLET_FLOW_TERMS = (
    "karta v mobilu", "kartu v mobilu", "mobilní karta", "mobilni karta",
    "přidat kartu do", "pridat kartu do", "nahrát kartu", "nahrat kartu",
    "mít kartu v mobilu", "mit kartu v mobilu",
    "apple pay karta", "google pay karta", "hodinky karta", "watch karta",
)
ABROAD_CARD_USAGE_TERMS = (
    "karta v zahraničí", "karta v zahranici", "karta v usa", "karta v eu",
    "kartou v zahraničí", "kartou v zahranici", "platba kartou v zahraničí",
    "platba kartou v zahranici", "zahraničí karta", "zahranici karta",
    "funguje karta v", "použití karty v zahraničí", "pouziti karty v zahranici",
    "zahraniční výběr", "zahranicni vyber",
)
CARD_BRAND_OVERVIEW_TERMS = (
    "máte visa", "mate visa", "máte mastercard", "mate mastercard",
    "visa nebo mastercard", "mastercard nebo visa",
    "jakou značku karty", "jakou znacku karty",
    "jakou kartu visa", "jakou kartu mastercard",
    "můžu mít visu", "muzu mít visu", "je visa", "jsou visa",
    "typ karty visa", "mastercard typ",
)

# --- Priority 2: Soft guidance detection patterns ---
SOFT_GUIDANCE_FAQ_TERMS = (
    "jak funguje", "jak se", "co je", "co to je",
    "kde najdu", "kde zjistím", "kde zjistim",
    "můžu", "muzu", "lze", "jde",
    "je možné", "je mozne",
    "potřebuju", "potrebuju", "chci",
    "poradíte", "poradite", "doporučíte", "doporucite",
    "máte", "mate",
    # Procedural
    "jak zvýš", "jak zvys", "jak sníž", "jak sniz",
    "jak změn", "jak zmen", "jak nastav",
    "jak zablokuj", "jak aktivuj", "jak zapn",
)


@dataclass(frozen=True)
class QueryProfile:
    labels: set[str] = field(default_factory=set)
    preferred_url_contains: tuple[str, ...] = ()
    penalized_url_contains: tuple[str, ...] = ()
    preferred_categories: tuple[str, ...] = ()
    preferred_chunk_types: tuple[str, ...] = ()
    preferred_document_types: tuple[str, ...] = ()
    bm25_weight: float = 0.4
    vector_weight: float = 0.6
    rerank_min_score: float = 0.0
    hybrid_top_k: int = 0


def classify_query(query: str) -> QueryProfile:
    q = query.lower()
    labels: set[str] = set()
    has_business_account_term = any(k in q for k in BUSINESS_ACCOUNT_TERMS)

    if any(k in q for k in ("poplatek", "poplatky", "cena", "stojí", "kolik", "sazebník", "ceník", "kč", "zdarma", "fee", "monthly", "maintenance")):
        labels.add("pricing")
    if any(k in q for k in ARCHIVE_QUERY_TERMS):
        labels.add("archived_requested")
    if any(k in q for k in PERSONAL_ACCOUNT_TERMS):
        labels.add("retail_banking")
        if not has_business_account_term:
            labels.add("personal_retail_account")
    elif "účet" in q or "ucet" in q:
        labels.add("retail_banking")
        if not has_business_account_term:
            labels.add("personal_retail_account")
    if has_business_account_term or any(k in q for k in ("právnick",)):
        labels.add("corporate_banking")
        labels.add("business_account")
        if any(k in q for k in ("podnikatel", "podnikatelsk", "osvč", "osvc", "živnostník", "zivnostnik")):
            labels.add("entrepreneur_account")
    has_catalog_intent = any(k in q for k in CATALOG_TERMS)
    has_credit_card_term = any(k in q for k in CREDIT_CARD_TERMS)
    has_card_overview_term = any(k in q for k in CARD_OVERVIEW_TERMS)

    if any(k in q for k in ("karta", "karty", "karet", "platební", "platebni", "limit karty", "kreditní", "kreditni", "kreditka", "kreditku", "kreditky", "kreditek", "debetní", "debetni", "výběr", "bankomat", "credit card")):
        labels.add("cards")
    if has_credit_card_term:
        labels.add("credit_card")
        labels.add("cards")
    if has_catalog_intent:
        labels.add("catalog_intent")
    if has_catalog_intent and (has_card_overview_term or ("cards" in labels and "plateb" in q)):
        labels.add("card_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
    if has_catalog_intent and "cards" in labels and "debet" not in q and (has_credit_card_term or has_card_overview_term or "card_overview" not in labels):
        labels.add("credit_card_catalog")
        labels.add("credit_card")
        labels.discard("card_overview")    # credit_card_catalog má vyšší prioritu v chain.py

    # --- General supported product overview detection ---
    has_account_overview = has_catalog_intent and any(k in q for k in ACCOUNT_OVERVIEW_TERMS)
    has_mortgage_overview = has_catalog_intent and any(k in q for k in MORTGAGE_OVERVIEW_TERMS)
    has_investment_overview = has_catalog_intent and any(k in q for k in INVESTMENT_OVERVIEW_TERMS)
    has_payment_overview = has_catalog_intent and any(k in q for k in PAYMENT_OVERVIEW_TERMS)
    has_rb_key_overview = any(k in q for k in RB_KEY_OVERVIEW_TERMS)
    has_sepa_swift_overview = any(k in q for k in SEPA_SWIFT_OVERVIEW_TERMS)

    if has_account_overview:
        labels.add("account_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("retail_banking")
    if has_mortgage_overview:
        labels.add("mortgage_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("mortgages")
    if has_investment_overview:
        labels.add("investment_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("investing")
    if has_payment_overview:
        labels.add("payment_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("payments")
    if has_rb_key_overview:
        labels.add("rb_key_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("rb_key")
        labels.add("support")
    if has_sepa_swift_overview:
        labels.add("sepa_swift_overview")
        labels.add("product_overview")
        labels.add("supported_domain")
        labels.add("sepa_swift")
        labels.add("payments")

    # credit_card_catalog má v chain.py nižší prioritu než card_overview a payment_overview
    # → odstraníme konflikty aby catalog strategie mohla vyhrát
    if "credit_card_catalog" in labels:
        labels.discard("card_overview")
        labels.discard("payment_overview")

    # General catalog-without-unsupported-intent → safe product overview.
    if has_catalog_intent and "product_overview" not in labels and not any(k in q for k in ("krypto", "bitcoin", "ethereum", "nft")):
        # If catalog_intent is present and no unsupported topics, add
        # product_overview + supported_domain as a safe default for
        # queries like "Co nabízíte?" in a banking context.
        labels.add("product_overview")
        labels.add("supported_domain")
    # --- Priority 3: Procedural flow routes ---
    if any(k in q for k in ACTIVATION_FLOW_TERMS):
        labels.add("activation_flow")
        labels.add("cards")
        labels.add("support")
        labels.add("faq")
    if any(k in q for k in CARD_LIMIT_FLOW_TERMS):
        labels.add("card_limit_flow")
        labels.add("cards")
        labels.add("support")
        labels.add("faq")
    if any(k in q for k in MOBILE_WALLET_FLOW_TERMS):
        labels.add("mobile_wallet_flow")
        labels.add("wallets")
        labels.add("cards")
        labels.add("support")
        labels.add("faq")
    if any(k in q for k in ABROAD_CARD_USAGE_TERMS):
        labels.add("abroad_card_usage")
        labels.add("cards")
        labels.add("support")
        labels.add("faq")
    if any(k in q for k in CARD_BRAND_OVERVIEW_TERMS):
        labels.add("card_brand_overview")
        labels.add("cards")
        labels.add("faq")

    # --- Priority 2: Soft guidance candidate detection ---
    # Soft guidance is tagged when the query is a FAQ/procedural/question
    # but NOT pricing, NOT unsupported, and NOT an overview intent.
    has_soft_guidance_candidate = (
        any(k in q for k in SOFT_GUIDANCE_FAQ_TERMS)
        and "pricing" not in labels
        and not any(k in q for k in ("krypto", "bitcoin", "ethereum", "nft"))
        and "product_overview" not in labels
    )
    if has_soft_guidance_candidate:
        labels.add("soft_guidance_candidate")

    if any(k in q for k in ("hypot", "úvěr na bydlení", "uver na bydleni")):
        labels.add("mortgages")
    if any(k in q for k in ("půjčk", "pujck", "úvěr", "uver", "kontokorent", "spotřebitelský", "spotrebitelsky", "refinancov", "rpsn")):
        labels.add("loans")
    if any(k in q for k in ("spoření", "sporeni", "spořicí", "sporici", "termínovaný vklad", "terminovany vklad", "stavební spoření", "stavebni sporeni", "úrok", "urok", "zhodnocení", "zhodnoceni", "vklad")):
        labels.add("savings")
        labels.add("supported_domain")
    if any(k in q for k in ("invest", "fond", "dip", "akcie", "dluhopis")):
        labels.add("investing")
    if any(k in q for k in ("phishing", "bezpečnost", "bezpecnost", "podvod", "zabezpečení", "zabezpeceni", "bezpečné bankovnictví", "bezpecne bankovnictvi", "smishing", "vishing", "podvodný", "podvodny", "falešný", "falesny", "heslo", "pin kód", "pin kod", "bezpečnostní", "bezpecnostni")):
        labels.add("security")
        labels.add("supported_domain")
    if any(k in q for k in ("raia", "asistentka", "bankovní identita", "bankovni identita", "rb klíč", "rb klic", "mobilní bankovnictví", "mobilni bankovnictvi", "internetové bankovnictví", "internetove bankovnictvi", "platba mobilem", "platba hodinkami", "platímpak", "platimpak", "platím pak", "platim pak", "odložená platba", "odlozena platba", "online služby", "online sluzby")):
        labels.add("online_services")
        labels.add("supported_domain")
        # online_services přebíjí generické activation_flow/cards aby se zabránilo
        # falešné klasifikaci follow-up dotazů jako karty
        labels.discard("activation_flow")
        labels.discard("cards")
    if any(k in q for k in ("platímpak", "platimpak", "platím pak", "platim pak", "odložená platba", "odlozena platba")):
        labels.add("loans")
        labels.add("online_services")
        labels.add("supported_domain")
    if any(k in q for k in FAQ_TERMS):
        labels.add("faq")
    if any(k in q for k in COMPLAINT_TERMS):
        labels.add("complaints")
        labels.add("support")
    if any(k in q for k in RB_KEY_TERMS):
        labels.add("rb_key")
        labels.add("support")
    if any(k in q for k in WALLET_TERMS):
        labels.add("wallets")
        labels.add("cards")
    if any(k in q for k in PAYMENT_RAIL_TERMS):
        labels.add("sepa_swift")
        labels.add("payments")
    if any(k in q for k in ("pojiště", "pojist", "cestovní pojištění")):
        labels.add("insurance")
    if any(k in q for k in ("jak", "změnit", "zmenit", "nastavit", "ztráta", "blokace", "podpora", "kontakt")):
        labels.add("support")

    preferred_urls: list[str] = []
    penalized_urls: list[str] = []
    preferred_categories: list[str] = []
    preferred_chunk_types: list[str] = []
    preferred_doc_types: list[str] = []
    bm25_weight = 0.4
    vector_weight = 0.6
    rerank_min_score = 0.0
    hybrid_top_k = 0

    if "pricing" in labels:
        bm25_weight = 0.65
        vector_weight = 0.35
        preferred_doc_types.append("pricing")
        preferred_chunk_types.extend(["pricing_row", "pricing", "table", "pdf_table"])
        rerank_min_score = 0.0
    if "support" in labels and "pricing" not in labels:
        bm25_weight = 0.3
        vector_weight = 0.7
        preferred_chunk_types.append("faq")
        rerank_min_score = -1.0
    if "faq" in labels and "pricing" not in labels:
        bm25_weight = min(bm25_weight, 0.35)
        vector_weight = max(vector_weight, 0.65)
        preferred_chunk_types.extend(["faq", "html", "text"])
        preferred_categories.extend(["faq", "support"])
        rerank_min_score = -1.0
    if "complaints" in labels:
        preferred_urls.extend(["reklamace", "stiznosti", "formulare"])
        preferred_categories.extend(["support", "complaints"])
    if "rb_key" in labels:
        preferred_urls.extend(["rb-klic", "rb-klíč", "mobilni", "bezpecnost"])
        preferred_categories.extend(["security", "digital", "support"])
    if "wallets" in labels:
        preferred_urls.extend(["apple-pay", "google-pay", "karty", "mobilni-platby"])
        preferred_categories.extend(["cards", "payments", "digital"])
    # --- Priority 3: Procedural flow route preferences ---
    if "activation_flow" in labels:
        preferred_categories.extend(["cards", "support", "faq"])
        preferred_urls.extend(["karty", "aktivace", "platebni-karty"])
        preferred_chunk_types.extend(["faq", "html", "section_text"])
        rerank_min_score = -10.0
    if "card_limit_flow" in labels:
        preferred_categories.extend(["cards", "support", "faq"])
        preferred_urls.extend(["karty", "limity", "platebni-karty"])
        preferred_chunk_types.extend(["faq", "html", "section_text"])
        rerank_min_score = -10.0
    if "mobile_wallet_flow" in labels:
        preferred_categories.extend(["cards", "payments", "digital", "support"])
        preferred_urls.extend(["karty", "apple-pay", "google-pay", "mobilni-platby", "virtualni-karta"])
        preferred_chunk_types.extend(["faq", "html", "section_text"])
        rerank_min_score = -10.0
    if "abroad_card_usage" in labels:
        preferred_categories.extend(["cards", "payments", "support", "foreign_payments"])
        preferred_urls.extend(["karty", "zahranicni-platby", "cestovani", "platebni-karty"])
        preferred_chunk_types.extend(["faq", "html", "section_text"])
        rerank_min_score = -10.0
    if "card_brand_overview" in labels:
        preferred_categories.extend(["cards", "faq"])
        preferred_urls.extend(["karty", "platebni-karty", "debetni-karty", "kreditni-karty"])
        preferred_chunk_types.extend(["faq", "html", "section_text"])
        rerank_min_score = -10.0
    if "sepa_swift" in labels:
        preferred_urls.extend(["sepa", "swift", "zahranicni-platby", "zahraniční-platby", "platby"])
        preferred_categories.extend(["payments", "foreign_payments"])
    if "retail_banking" in labels:
        preferred_urls.append("/osobni/")
        preferred_categories.extend(["retail", "accounts", "retail_banking"])
        penalized_urls.extend(["/firmy/", "/podnikatele/", "corporate"])
    if "personal_retail_account" in labels:
        preferred_categories.insert(0, "retail")
        preferred_doc_types.append("pricing")
    if "corporate_banking" in labels:
        preferred_urls.extend(["/firmy/", "/podnikatele/"])
        preferred_categories.extend(["business", "corporate"])
    if "cards" in labels:
        preferred_categories.append("cards")
        preferred_urls.append("/karty")
    if "card_overview" in labels:
        preferred_categories.extend(["cards", "payments", "digital"])
        preferred_urls.extend(["karty", "platebni-karty", "debetni-karty", "kreditni-karty", "virtualni-karta"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pricing", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "account_overview" in labels:
        preferred_categories.extend(["retail", "accounts", "retail_banking"])
        preferred_urls.extend(["osobni", "ucty", "ekonto", "bezny-ucet", "podnikatele", "firmy"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "mortgage_overview" in labels:
        preferred_categories.extend(["mortgages", "hypoteky"])
        preferred_urls.extend(["hypoteky", "hypoteka"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "investment_overview" in labels:
        preferred_categories.extend(["investments", "investice"])
        preferred_urls.extend(["investice", "fondy", "dip"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "payment_overview" in labels or "sepa_swift_overview" in labels:
        preferred_categories.extend(["payments", "foreign_payments", "digital"])
        preferred_urls.extend(["platby", "sepa", "swift", "zahranicni-platby", "zahraniční-platby"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "rb_key_overview" in labels:
        preferred_categories.extend(["security", "digital", "support"])
        preferred_urls.extend(["rb-klic", "rb-klíč", "mobilni", "bezpecnost"])
        preferred_chunk_types.extend(["section_text", "html", "faq", "pdf_text"])
        bm25_weight = max(bm25_weight, 0.50)
        vector_weight = min(vector_weight, 0.50)
        rerank_min_score = -10.0
    if "credit_card" in labels:
        preferred_categories.extend(["cards", "credit_cards", "kreditni_karty"])
        preferred_urls.extend(["kreditni-karty", "kreditni-karta", "kreditni", "credit-card", "/karty"])
        bm25_weight = max(bm25_weight, 0.45)
        vector_weight = min(vector_weight, 0.55)
    if "credit_card_catalog" in labels:
        preferred_chunk_types.extend(["section_text", "html", "faq", "pricing"])
        rerank_min_score = -10.0
    if "mortgages" in labels:
        preferred_categories.append("mortgages")
        preferred_urls.append("/hypotek")
    if "loans" in labels:
        preferred_categories.extend(["loans", "pujcky"])
        preferred_urls.extend(["/pujcky", "/uvery", "pujcka"])
    if "investing" in labels:
        preferred_categories.append("investments")
        preferred_urls.extend(["investice", "fondy", "dip"])
    if "savings" in labels:
        preferred_categories.extend(["savings", "sporeni"])
        preferred_urls.extend(["/sporeni", "/sporici", "vklad", "zhodnoceni"])
    if "insurance" in labels:
        preferred_categories.append("insurance")
    if "security" in labels:
        preferred_urls.extend(["bezpecne-bankovnictvi", "bezpecnost", "phishing"])
    if "online_services" in labels:
        preferred_urls.extend(["asistentka-raia", "bankovni-identita", "rb-klic", "mobilni-bankovnictvi", "internetove-bankovnictvi"])
    if "loans" in labels and "online_services" in labels:
        preferred_urls.extend(["pujcky", "osobni/pujcky", "platimpak"])
        preferred_categories.extend(["loans", "pujcky"])

    # ---------------------------------------------------------------------
    # 1️⃣  Fix: pokud jsou současně přítomny labely "catalog_intent" a "product_overview",
    #     odebereme automatické labely "faq" a "support" a nastavíme explicitní
    #     preferované typy dokumentů (product‑related).
    # ---------------------------------------------------------------------
    if "catalog_intent" in labels and "product_overview" in labels:
        # odebereme případně dříve přidané labely
        labels.discard("faq")
        labels.discard("support")
        # explicitně definujeme, že chceme pouze produktové typy
        preferred_doc_types = (
            "product_page",
            "account_product",
            "credit_card",
            "mortgage_product",
            "product_catalog",
        )
        if "mortgages" in labels:
            rerank_min_score = -3.0
            hybrid_top_k = 20
        if "loans" in labels or "pujcky" in labels:
            rerank_min_score = -4.0
            hybrid_top_k = 20
        if "investing" in labels:
            rerank_min_score = -4.0
            hybrid_top_k = 20
        if "savings" in labels:
            rerank_min_score = -4.0
            hybrid_top_k = 20
        if "security" in labels:
            rerank_min_score = -4.0
            hybrid_top_k = 20
        if "online_services" in labels:
            rerank_min_score = -6.0
            hybrid_top_k = 20
    # Loans/investing/savings/security/online_services threshold mimo catalog_intent blok
    if "online_services" in labels and rerank_min_score > -6.0:
        rerank_min_score = -6.0
        if hybrid_top_k < 20:
            hybrid_top_k = 20
    if ("loans" in labels or "pujcky" in labels or "investing" in labels or "savings" in labels or "security" in labels) and rerank_min_score > -4.0:
        rerank_min_score = -4.0
        if hybrid_top_k < 20:
            hybrid_top_k = 20
    # ---------------------------------------------------------------------
    # Vytvoření a vrácení QueryProfile (původní chování)
    # ---------------------------------------------------------------------
    return QueryProfile(
        labels=labels or {"general"},
        preferred_url_contains=tuple(dict.fromkeys(preferred_urls)),
        penalized_url_contains=tuple(dict.fromkeys(penalized_urls)),
        preferred_categories=tuple(dict.fromkeys(preferred_categories)),
        preferred_chunk_types=tuple(dict.fromkeys(preferred_chunk_types)),
        preferred_document_types=tuple(dict.fromkeys(preferred_doc_types)),
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        rerank_min_score=rerank_min_score,
        hybrid_top_k=hybrid_top_k,
    )


def expand_query(query: str, profile: QueryProfile | None = None) -> str:
    """Add high-signal Czech banking/pricing synonyms for sparse/dense recall."""
    profile = profile or classify_query(query)
    q = query.lower()
    terms: list[str] = []
    if "pricing" in profile.labels:
        terms.extend(["poplatek", "cena", "stojí", "zdarma", "kč"])
    if "ekonto" in q or "ekonta" in q:
        terms.extend(["eKonto", "ekonto", "ekonta", "vedení účtu", "vedeni uctu", "běžný účet", "bezny ucet"])
    if any(k in q for k in ("vedení", "vedeni", "účtu", "uctu")):
        terms.extend(["vedení účtu", "vedeni uctu", "měsíční poplatek", "mesicni poplatek"])
    if "complaints" in profile.labels:
        terms.extend([
            "reklamace platby", "reklamace transakce", "neoprávněná transakce",
            "chargeback", "karetní reklamace", "vrácení platby", "dispute transaction",
            "stížnost na platbu", "reklamace karetní transakce", "reklamovat",
            "formulář reklamace", "kartová transakce",
        ])
    if "rb_key" in profile.labels:
        terms.extend(["RB klíč", "RB klic", "mobilní aplikace", "autorizace", "potvrzení platby", "aktivace"])
    if "wallets" in profile.labels:
        terms.extend(["Apple Pay", "Google Pay", "mobilní platby", "platební karta", "digital wallet"])
    if "card_overview" in profile.labels:
        terms.extend([
            "platební karty", "debetní karta", "kreditní karta", "Mastercard",
            "Visa", "virtuální karta", "karty Raiffeisenbank", "debetní karty k účtu",
        ])
    if "account_overview" in profile.labels:
        terms.extend([
            "běžný účet", "osobní účet", "podnikatelský účet", "základní účet",
            "ekonto", "aktivní účet", "firemní účet",
        ])
    if "mortgage_overview" in profile.labels:
        terms.extend([
            "hypotéka", "úvěr na bydlení", "refinancování", "fixace",
            "hypoteční úvěr",
        ])
    if "investment_overview" in profile.labels:
        terms.extend([
            "investice", "fondy", "podílové fondy", "rizika investování",
            "dluhopis", "DIP",
        ])
    if "rb_key_overview" in profile.labels:
        terms.extend([
            "RB klíč", "mobilní aplikace", "ověření", "přihlášení",
            "autorizace", "bezpečnost",
        ])
    if "payment_overview" in profile.labels:
        terms.extend([
            "platba", "převod", "tuzemská platba", "zahraniční platba",
            "platební metody",
        ])
    if "sepa_swift_overview" in profile.labels:
        terms.extend([
            "SEPA", "SWIFT", "zahraniční platba", "IBAN", "BIC",
            "EUR platba",
        ])
    if "credit_card" in profile.labels:
        terms.extend([
            "kreditka", "kreditku", "kreditky", "kreditní karta", "kreditní karty",
            "splátková karta", "karta na splátky", "Mastercard kreditní karta",
            "Visa kreditní karta", "credit card", "Kreditní karta EASY",
            "Kreditní karta STYLE", "Kreditní karta RB PREMIUM", "Kreditní karta Visa Gold",
            "Kreditní karta O2 RB",
        ])
    if "loans" in profile.labels and "online_services" in profile.labels:
        terms.extend(["PlatímPak", "platímpak", "platím pak", "odložená platba", "platimpak", "odložená platba nákupy"])
    if "sepa_swift" in profile.labels:
        terms.extend(["SEPA", "SWIFT", "zahraniční platba", "EUR platba", "IBAN", "BIC"])
    if "investing" in profile.labels:
        terms.extend(["investice", "fondy", "DIP", "rizika", "prodej investice", "cenné papíry"])
    if "faq" in profile.labels:
        terms.extend(["návod", "postup", "často kladené dotazy", "FAQ", "jak postupovat"])
    if "activation_flow" in profile.labels:
        terms.extend(["aktivace karty", "aktivovat kartu", "zapnout kartu",
                       "první použití karty", "začít používat kartu"])
    if "card_limit_flow" in profile.labels:
        terms.extend(["limit karty", "zvýšení limitu", "navýšení limitu",
                       "maximální limit", "denní limit"])
    if "mobile_wallet_flow" in profile.labels:
        terms.extend(["Apple Pay", "Google Pay", "mobilní platby",
                       "přidat kartu do Apple Pay", "přidat kartu do Google Pay"])
    if "abroad_card_usage" in profile.labels:
        terms.extend(["zahraniční platba kartou", "zahraniční výběr z bankomatu",
                       "cestování s kartou", "karta v zahraničí"])
    if "card_brand_overview" in profile.labels:
        terms.extend(["Visa", "Mastercard", "platební značka", "typ karty",
                       "debetní karta Mastercard", "debetní karta Visa"])
    # Preserve original phrasing first, append unique expansions for BM25 exact-match recall.
    unique = [term for term in dict.fromkeys(terms) if term.lower() not in q]
    return " ".join([query, *unique]).strip()


def source_priority(doc: Document, profile: QueryProfile) -> tuple[float, list[str]]:
    """Return additive boost/penalty and human-readable reasons."""
    md = doc.metadata
    url = str(md.get("source_url") or md.get("url") or md.get("source") or "").lower()
    title = str(md.get("title") or md.get("file_name") or "").lower()
    filename = str(md.get("file_name") or md.get("source") or "").lower()
    category = str(md.get("category") or "").lower()
    chunk_type = str(md.get("chunk_type") or "").lower()
    document_type = str(md.get("document_type") or "").lower()
    content = doc.page_content.lower()[:1200]
    metadata_terms = " ".join(str(md.get(k) or "") for k in ("product_name", "fee_type", "fee_value", "table_title"))
    hay = " ".join([url, title, filename, metadata_terms.lower(), content])
    score = 0.0
    reasons: list[str] = []

    if document_type in profile.preferred_document_types:
        score += 0.035; reasons.append(f"document_type={document_type}")
    if chunk_type in profile.preferred_chunk_types:
        score += 0.300 if chunk_type == "pricing_row" else 0.030; reasons.append(f"chunk_type={chunk_type}")
    if category in profile.preferred_categories:
        score += 0.060 if category == "retail" else 0.025; reasons.append(f"category={category}")
    if "retail_banking" in profile.labels and "corporate_banking" not in profile.labels and category == "corporate":
        score -= 0.140; reasons.append("hard corporate category penalty")
    if "retail_banking" in profile.labels and "corporate_banking" not in profile.labels and category == "retail" and document_type == "pricing":
        score += 0.080; reasons.append("retail pricing preferred")
    if "retail_banking" in profile.labels and "corporate_banking" not in profile.labels and category in {"investing", "investments", "insurance", "mortgages", "corporate", "business"}:
        score -= 0.120; reasons.append(f"non-retail category penalty={category}")
    if "pricing" in profile.labels and chunk_type == "pricing_row":
        score += 0.300; reasons.append("atomic pricing_row preferred")
        if md.get("product_name"):
            score += 0.035; reasons.append("pricing_row product_name present")
        if md.get("fee_type") and md.get("fee_value"):
            score += 0.050; reasons.append("pricing_row fee_type/value present")
    if "retail_banking" in profile.labels and "pricing" in profile.labels:
        pricing_type = str(md.get("pricing_type") or "").lower()
        if pricing_type == "account_fee":
            score += 0.070; reasons.append("account_fee pricing preferred")
        elif pricing_type and pricing_type != "generic_pricing":
            score -= 0.025; reasons.append(f"non-account pricing_type={pricing_type}")
    if "personal_retail_account" in profile.labels:
        if any(term in hay for term in PERSONAL_SOURCE_TERMS):
            score += 0.120; reasons.append("personal retail source preferred")
        if any(term in hay for term in BUSINESS_SOURCE_TERMS):
            score -= 0.220; reasons.append("business/FOP/corp source penalty")
        if category == "retail" and document_type == "pricing":
            score += 0.100; reasons.append("personal retail pricing category")
    quality = detect_chunk_quality(doc.page_content)
    if str(md.get("chunk_quality") or "").lower() == "bad_table_row":
        quality = "bad_table_row"
    if quality == "bad_pdf_extraction":
        score -= 0.180; reasons.append("bad_pdf_extraction penalty")
    elif quality == "bad_table_row":
        score -= 0.220; reasons.append("bad_table_row penalty")
    freshness_score, archived_penalty, freshness_reasons = freshness_priority(doc, profile)
    score += freshness_score + archived_penalty
    reasons.extend(freshness_reasons)
    for needle in profile.preferred_url_contains:
        if needle in url:
            score += 0.045; reasons.append(f"url contains {needle}")
    for needle in profile.penalized_url_contains:
        if needle in url or needle in title:
            score -= 0.060; reasons.append(f"penalized {needle}")

    if "retail_banking" in profile.labels:
        if re.search(r"\b(aktivní účet|aktivni ucet|běžný účet|bezny ucet|ekonto|osobní účet|osobni ucet)\b", content + " " + title):
            score += 0.040; reasons.append("retail account terms")
        if any(k in content + " " + title for k in ("corp", "corporate", "firemní", "podnikatel", "právnick")):
            score -= 0.035; reasons.append("corporate wording penalty")
    if "pricing" in profile.labels and any(k in content for k in ("kč", "poplatek", "zdarma", "měsíčně", "ceník", "sazebník")):
        score += 0.025; reasons.append("pricing terms in content")
    if "faq" in profile.labels and (chunk_type == "faq" or any(k in hay for k in ("faq", "často", "casto", "jak", "návod", "navod"))):
        score += 0.120; reasons.append("faq_priority_used")
    if "complaints" in profile.labels and any(k in hay for k in ("reklamac", "stížnost", "stiznost", "formulář", "formular")):
        score += 0.180; reasons.append("complaint metadata/content boost")
    if "rb_key" in profile.labels and any(k in hay for k in ("rb klíč", "rb klic", "mobilní klíč", "mobilni klic", "autorizace")):
        score += 0.180; reasons.append("rb_key metadata/content boost")
    if "wallets" in profile.labels and any(k in hay for k in ("apple pay", "google pay", "mobilní plat", "mobilni plat", "karty")):
        score += 0.160; reasons.append("wallet metadata/content boost")
    if "card_overview" in profile.labels:
        card_terms = ("platební karta", "platebni karta", "platební karty", "debetní", "debetni", "kreditní", "kreditni", "mastercard", "visa", "virtuální karta", "virtualni karta", "kreditni-karty", "debetni-karty")
        if any(k in hay for k in card_terms):
            score += 0.240; reasons.append("card overview metadata/content boost")
        if "uniqa" in hay or "pojišťovna" in hay or "pojistovna" in hay:
            score -= 0.180; reasons.append("cross-domain insurance penalty for card overview")
    if "account_overview" in profile.labels:
        account_terms = ("běžný účet", "bezny ucet", "osobní účet", "osobni ucet", "ekonto", "aktivní účet", "aktivni ucet", "podnikatelský účet", "podnikatelsky ucet", "firemní účet", "firemni ucet")
        if any(k in hay for k in account_terms):
            score += 0.240; reasons.append("account overview metadata/content boost")
        if "uniqa" in hay or "pojišťovna" in hay or "hypot" in hay:
            score -= 0.180; reasons.append("cross-domain penalty for account overview")
    if "mortgage_overview" in profile.labels or "mortgages" in profile.labels:
        mortgage_terms = ("hypotéka", "hypoteka", "hypoteční", "hypotecni", "úvěr na bydlení", "uver na bydleni", "refinancování", "refinancovani")
        if any(k in hay for k in mortgage_terms):
            score += 0.240; reasons.append("mortgage metadata/content boost")
        if "uniqa" in hay or "pojišťovna" in hay:
            score -= 0.180; reasons.append("cross-domain insurance penalty for mortgage overview")
    if "investment_overview" in profile.labels:
        investment_terms = ("investice", "fondy", "podílové fondy", "podilove fondy", "dluhopis", "dip", "akcie")
        if any(k in hay for k in investment_terms):
            score += 0.240; reasons.append("investment overview metadata/content boost")
        if "uniqa" in hay or "pojišťovna" in hay:
            score -= 0.180; reasons.append("cross-domain insurance penalty for investment overview")
    if "payment_overview" in profile.labels or "sepa_swift_overview" in profile.labels:
        payment_terms = ("platba", "převod", "prevod", "tuzemská", "zahraniční", "zahranicni", "sepa", "swift", "iban", "bic", "platební metody", "platebni metody")
        if any(k in hay for k in payment_terms):
            score += 0.240; reasons.append("payment overview metadata/content boost")
        if "uniqa" in hay or "pojišťovna" in hay:
            score -= 0.180; reasons.append("cross-domain insurance penalty for payment overview")
    if "rb_key_overview" in profile.labels:
        rb_key_terms = ("rb klíč", "rb klic", "rb-klic", "rb-klíč", "mobilní klíč", "mobilni klic", "mobilní aplikace", "mobilni aplikace", "autorizace", "přihlášení", "prihlaseni")
        if any(k in hay for k in rb_key_terms):
            score += 0.240; reasons.append("rb_key overview metadata/content boost")
    if "credit_card" in profile.labels:
        credit_terms = ("kreditni-karty", "kreditní karta", "kreditni karta", "kreditní karty", "kreditka", "mastercard", "visa", "o2 rb", "rb premium", "style", "easy")
        if any(k in hay for k in credit_terms):
            score += 0.260; reasons.append("boosted_product_group=kreditni_karta")
        if any(k in hay for k in ("debetní", "debetni")) and not any(k in hay for k in ("kreditní", "kreditni", "kreditka")):
            score -= 0.100; reasons.append("debit card penalty for credit_card query")
    if "sepa_swift" in profile.labels and any(k in hay for k in ("sepa", "swift", "iban", "bic", "zahraniční", "zahranicni")):
        score += 0.160; reasons.append("sepa_swift metadata/content boost")
    if "investing" in profile.labels and any(k in hay for k in ("invest", "fond", "dip", "cenné papíry", "cenne papiry")):
        score += 0.120; reasons.append("investing metadata/content boost")

    # Priority 1: Authority scoring — additive boost/penalty based on
    # document type, URL, title, and content signals.
    authority_boost, authority_tier, authority_reasons = score_document_authority(doc)
    score += authority_boost
    reasons.append(f"authority={authority_tier} boost={authority_boost:+.4f}")

    if not reasons:
        reasons.append("base hybrid relevance")
    return score, reasons


def freshness_priority(doc: Document, profile: QueryProfile) -> tuple[float, float, list[str]]:
    md = doc.metadata
    document_type = str(md.get("document_type") or "").lower()
    if "pricing" not in profile.labels and document_type != "pricing":
        return 0.0, 0.0, []

    is_archived = bool(md.get("is_archived") or md.get("is_discontinued"))
    title = str(md.get("title") or "").lower()
    content = doc.page_content.lower()[:800]
    if any(term in title + " " + content for term in ("již nenabízené", "jiz nenabizene", "discontinued", "archived", "staré produkty", "stare produkty")):
        is_archived = True

    year = md.get("document_year")
    try:
        year_int = int(year) if year else None
    except Exception:
        year_int = None

    freshness_score = 0.0
    archived_penalty = 0.0
    reasons: list[str] = []

    if not is_archived:
        freshness_score += 0.300
        reasons.append("fresh active pricing +0.300")
        if year_int:
            # Small recency boost capped to avoid overwhelming semantic relevance.
            freshness_score += max(0.0, min(0.100, (year_int - 2020) * 0.015))
            reasons.append(f"document_year={year_int}")
    elif "archived_requested" not in profile.labels:
        archived_penalty -= 0.500
        reasons.append("archived/discontinued pricing -0.500")

    return freshness_score, archived_penalty, reasons


def is_archived_doc(doc: Document) -> bool:
    md = doc.metadata
    if md.get("is_archived") or md.get("is_discontinued"):
        return True
    hay = " ".join([str(md.get("title") or ""), str(md.get("file_name") or ""), doc.page_content[:800]]).lower()
    return any(term in hay for term in ("již nenabízené", "jiz nenabizene", "discontinued", "archived", "staré produkty", "stare produkty"))


def detect_chunk_quality(text: str) -> str:
    sample = text[:2500]
    tokens = re.findall(r"\S+", sample)
    if len(tokens) < 20:
        return "ok"
    single_char = sum(1 for token in tokens if len(token.strip(".,;:()[]{}|")) == 1)
    single_ratio = single_char / max(1, len(tokens))
    spaced_word_patterns = (
        r"\b[zv]\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽa-záčďéěíňóřšťúůýž](?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽa-záčďéěíňóřšťúůýž]){2,}\b",
        r"\bp\s+r\s+o\s+v\b",
        r"\bU\s+S\s+D\b",
        r"\bz\s+V\s+e\s+c\s+h\s+n\b",
    )
    if single_ratio > 0.33 or any(re.search(pattern, sample) for pattern in spaced_word_patterns):
        return "bad_pdf_extraction"
    return "ok"


def is_corporate_doc(doc: Document) -> bool:
    md = doc.metadata
    category = str(md.get("category") or "").lower()
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or md.get("source") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        doc.page_content[:1000],
    ]).lower()
    return category == "corporate" or any(k in hay for k in BUSINESS_SOURCE_TERMS + BUSINESS_ACCOUNT_TERMS)


def is_retail_doc(doc: Document) -> bool:
    md = doc.metadata
    category = str(md.get("category") or "").lower()
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or md.get("source") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        doc.page_content[:1000],
    ]).lower()
    return category == "retail" or "/osobni/" in hay or any(k in hay for k in ("osobní", "osobni", "aktivní účet", "aktivni ucet", "ekonto", "ekonta", "běžný účet", "bezny ucet"))


def is_personal_retail_doc(doc: Document) -> bool:
    return is_retail_doc(doc) and not is_corporate_doc(doc)


# ---------------------------------------------------------------------------
# Document Authority Scoring (Priority 1)
# ---------------------------------------------------------------------------

# Authority tiers — higher = more authoritative for banking FAQ/product retrieval
DOCUMENT_AUTHORITY_TIERS: dict[str, float] = {
    "product_page":       1.0,   # RB product detail / category page
    "faq_support_page":   0.9,   # FAQ / support / help / knowledge page
    "current_pricing":    0.8,   # Current pricing PDF or page
    "current_pdf":        0.7,   # Current non-pricing PDF (annual report, terms)
    "generic_page":       0.5,   # Generic web page / article
    "historical_pdf":     0.4,   # Historical / out-of-date document
    "migration_notice":   0.2,   # Migration / change notice
    "archived_legal":     0.1,   # Archived / legal-only document
    "unknown":            0.5,   # Default
}

# URL pattern -> authority tier
_AUTHORITY_URL_TIERS: list[tuple[str, str]] = [
    # Product pages (highest)
    (r"rb\.cz/(osobni|firmy|podnikatele)/[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)?$", "product_page"),
    (r"rb\.cz/(karty|hypoteky|investice|ucty|sporeni|pozicky)", "product_page"),
    # FAQ / support
    (r"(faq|casto|pomoc|podpora|kontakt|napoveda)", "faq_support_page"),
    (r"/faq/", "faq_support_page"),
    (r"/podpora/", "faq_support_page"),
    (r"/napoveda/", "faq_support_page"),
    # Pricing
    (r"(cenik|sazebnik|sazebník|cenník|cennik)", "current_pricing"),
    (r"/ceny/", "current_pricing"),
    # Migration
    (r"(migrac|change.*notice|zmena|změna|prechod|přechod)", "migration_notice"),
    # Archived
    (r"(archiv|discontinued|history|historic)", "archived_legal"),
]

_AUTHORITY_TITLE_TIERS: list[tuple[str, str]] = [
    (r"(současn|soucasn|nový|novy|platný|platny|aktuáln)", "current_pricing"),
    (r"(ceník|cenik|sazebník|sazebnik|cenník|cennik)", "current_pricing"),
    (r"(faq|často|casto|nejčastější|nejcastejsi)", "faq_support_page"),
    (r"(migračn|migracn|změn|zmen|přechod|prechod)", "migration_notice"),
    (r"(archiv|historick|discontinued|star)", "archived_legal"),
]

_MIGRATION_KEYWORDS = ("migračn", "migracn", "změna", "zmena", "přechod", "prechod",
                       "change notice", "migration", "nový ceník", "novy cenik")
_ARCHIVED_KEYWORDS = ("archiv", "discontinued", "již nenabíz", "jiz nenabiz",
                      "staré produkty", "stare produkty", "historický", "historicky")
_CURRENT_KEYWORDS = ("aktuáln", "současn", "soucasn", "nový ceník", "novy cenik",
                     "2024", "2025", "2026")


def _classify_document_authority(doc: Document) -> tuple[str, float, list[str]]:
    """Classify a document into an authority tier and return (tier, score, reasons).

    Uses metadata (document_type, category, chunk_type) first, then falls back
    to heuristic URL, title, and filename pattern matching.
    """
    md = doc.metadata
    url = str(md.get("source_url") or md.get("url") or md.get("source") or "").lower()
    title = str(md.get("title") or "").lower()
    filename = str(md.get("file_name") or "").lower()
    doc_type = str(md.get("document_type") or "").lower()
    category = str(md.get("category") or "").lower()
    chunk_type = str(md.get("chunk_type") or "").lower()
    hay = " ".join([url, title, filename])
    reasons: list[str] = []

    # 1. Metadata-based signals
    if doc_type == "pricing":
        # Check if current or historical
        if any(k in hay for k in _MIGRATION_KEYWORDS):
            reasons.append("authority=migration_notice (pricing + migration)")
            return "migration_notice", DOCUMENT_AUTHORITY_TIERS["migration_notice"], reasons
        if any(k in hay for k in _ARCHIVED_KEYWORDS):
            reasons.append("authority=historical_pdf (pricing + archived)")
            return "historical_pdf", DOCUMENT_AUTHORITY_TIERS["historical_pdf"], reasons
        is_current = any(k in hay for k in _CURRENT_KEYWORDS)
        if is_current or category in ("retail", "accounts", "retail_banking"):
            reasons.append("authority=current_pricing (pricing + current/retail)")
            return "current_pricing", DOCUMENT_AUTHORITY_TIERS["current_pricing"], reasons
        # Default pricing PDF
        reasons.append("authority=current_pricing (default pricing)")
        return "current_pricing", DOCUMENT_AUTHORITY_TIERS["current_pricing"], reasons

    if doc_type == "faq" or chunk_type == "faq":
        reasons.append("authority=faq_support_page (document_type/category faq)")
        return "faq_support_page", DOCUMENT_AUTHORITY_TIERS["faq_support_page"], reasons

    # 2. URL pattern matching
    for pattern, tier in _AUTHORITY_URL_TIERS:
        if re.search(pattern, url):
            reasons.append(f"authority={tier} (url pattern)")
            return tier, DOCUMENT_AUTHORITY_TIERS[tier], reasons

    # 3. Title/filename pattern matching
    for pattern, tier in _AUTHORITY_TITLE_TIERS:
        if re.search(pattern, title):
            reasons.append(f"authority={tier} (title match)")
            return tier, DOCUMENT_AUTHORITY_TIERS[tier], reasons
        if re.search(pattern, filename):
            reasons.append(f"authority={tier} (filename match)")
            return tier, DOCUMENT_AUTHORITY_TIERS[tier], reasons

    # 4. Content/keyword-based classification
    if any(k in hay for k in _MIGRATION_KEYWORDS):
        reasons.append("authority=migration_notice (keyword)")
        return "migration_notice", DOCUMENT_AUTHORITY_TIERS["migration_notice"], reasons
    if any(k in hay for k in _ARCHIVED_KEYWORDS):
        reasons.append("authority=archived_legal (keyword)")
        return "archived_legal", DOCUMENT_AUTHORITY_TIERS["archived_legal"], reasons
    if any(k in hay for k in _CURRENT_KEYWORDS):
        reasons.append(f"authority=current_pdf (current keyword)")
        return "current_pdf", DOCUMENT_AUTHORITY_TIERS["current_pdf"], reasons

    # 5. Category-based inference
    if category in ("support", "faq", "help"):
        reasons.append("authority=faq_support_page (category)")
        return "faq_support_page", DOCUMENT_AUTHORITY_TIERS["faq_support_page"], reasons
    if category in ("retail", "accounts", "cards", "payments", "mortgages", "investments"):
        reasons.append("authority=product_page (category)")
        return "product_page", DOCUMENT_AUTHORITY_TIERS["product_page"], reasons

    # 6. Default — generic page / current PDF
    reasons.append("authority=unknown (default)")
    return "unknown", DOCUMENT_AUTHORITY_TIERS["unknown"], reasons


def score_document_authority(doc: Document) -> tuple[float, str, list[str]]:
    """Return (authority_boost, authority_tier, reasons) for a document.

    The boost is meant to be additive in source_priority(). It maps the
    authority tier to a gain in [−0.30, +0.30] range.
    """
    tier, base, reasons = _classify_document_authority(doc)

    # Scale from [0.1..1.0] to [-0.30..+0.30] centered at 0.50 → 0.0
    boost = (base - 0.5) * 0.6
    boost = round(max(-0.30, min(0.30, boost)), 4)

    return boost, tier, reasons


# ---------------------------------------------------------------------------
# Priority 2 — Source Normalization UX
# ---------------------------------------------------------------------------

_SOURCE_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # More specific categories checked first to avoid false matches
    "pricing": [
        "sazebnik", "cenik", "poplatky", "ceník", "sazebník",
        "pricing", "fee-schedule",
    ],
    "legal": [
        "podminky", "vseobecne", "obchodni", "smluvni",
        "informacni-povinnost", "legal", "terms",
    ],
    "archived": [
        "archiv", "archive", "archived", "migrace", "migration",
        "historical", "historie",
    ],
    "migration": [
        "migrace", "migration", "prechod", "prevod",
    ],
    "faq_support": [
        "faq", "casto-kladene-dotazy", "navod", "manual",
        "podpora", "support", "jak-na-to",
    ],
    "product_page": [
        "produkt", "product", "kreditni-karty", "debetni-karty",
        "osobni-ucet", "bezny-ucet", "hypoteka", "investice",
    ],
}

_SOURCE_LABEL_MAP: dict[str, str] = {
    "product_page": "Produktová stránka",
    "faq_support": "FAQ / Návod",
    "pricing": "Ceník",
    "legal": "Obchodní podmínky",
    "archived": "Archivní",
    "migration": "Migrační dokument",
}


def _extract_year(text: str) -> int | None:
    """Extract a 4-digit year (1950–2099) from text."""
    if not text:
        return None
    matches = re.findall(r"\b(19[5-9]\d|20[0-4]\d|2050)\b", text)
    if matches:
        return int(matches[0])
    return None


def _guess_source_category(doc: Document) -> str:
    """Classify source into a UX category based on metadata heuristics.

    Returns one of: product_page, faq_support, pricing, legal, archived, unknown.
    """
    md = doc.metadata
    url = str(md.get("source_url") or md.get("url") or "").lower()
    title = str(md.get("title") or "").lower()
    filename = str(md.get("file_name") or "").lower()
    category = str(md.get("category") or "").lower()
    chunk_type = str(md.get("chunk_type") or "").lower()
    document_type = str(md.get("document_type") or "").lower()

    # Do NOT include document_type in hay — it's an internal routing field, not a
    # content signal. Including it would cause false matches (e.g. "product_page"
    # matching the "product" keyword).
    hay = f"{url} {title} {filename} {category} {chunk_type}"

    # Check archived first (overrides other categories)
    if is_archived_doc(doc):
        return "archived"

    for cat, keywords in _SOURCE_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in hay:
                return cat

    # Fallback heuristics
    if chunk_type == "pricing_row" or document_type == "pricing":
        return "pricing"
    if chunk_type == "faq":
        return "faq_support"
    if category in ("retail", "corporate", "business") and document_type:
        return "product_page"

    return "unknown"


def _build_human_title(doc: Document) -> str:
    """Build a human-readable title from metadata.

    Priority:
      1. Existing title (if not a hash/technical artifact)
      2. URL path segments (cleaned)
      3. Filename (cleaned)
      4. Category + chunk_type fallback
    """
    md = doc.metadata
    title = str(md.get("title") or "").strip()
    url = str(md.get("source_url") or md.get("url") or "").strip()
    filename = str(md.get("file_name") or "").strip()
    category = str(md.get("category") or "").strip()
    chunk_type = str(md.get("chunk_type") or "").strip()

    # Is the title a hash/technical artifact?
    def _is_hash(s: str) -> bool:
        """Heuristic: long hex strings are technical artifacts."""
        if len(s) < 10:
            return False
        hex_chars = sum(1 for ch in s if ch in "0123456789abcdef")
        return hex_chars / max(len(s), 1) > 0.75

    def _clean_filename(fn: str) -> str:
        """Convert kebab/snake case filename to human readable."""
        name = fn.rsplit(".", 1)[0] if "." in fn else fn  # strip extension
        # Remove hash segments (e.g. _a043bb3907)
        name = re.sub(r"_[a-f0-9]{8,}", "", name)
        name = re.sub(r"[_-]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:80]

    def _clean_url_path(u: str) -> str:
        """Extract meaningful path segments from RB URL."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(u)
            path = parsed.path.strip("/")
            segments = [s for s in path.split("/") if s and s not in (
                "cs", "en", "www.rb.cz", "rb.cz", "attachments",
                "documents", "files", "download",
            )]
            if not segments:
                return ""
            # Convert kebab-case segments
            readable = " — ".join(
                re.sub(r"[-_]", " ", s).strip().title()
                for s in segments[-3:]
            )
            return readable[:80]
        except Exception:
            return ""

    # Priority 1: Use existing title if it's not a hash
    if title and not _is_hash(title) and len(title) > 5:
        return _clean_filename(title)

    # Priority 2: Build from URL path
    url_title = _clean_url_path(url)
    if url_title:
        return url_title

    # Priority 3: Clean filename
    if filename and not _is_hash(filename):
        cleaned = _clean_filename(filename)
        if cleaned and len(cleaned) > 3:
            return cleaned

    # Priority 4: Category-based fallback
    category_map = {
        "retail": "Produktová stránka — Retail",
        "corporate": "Produktová stránka — Corporate",
        "business": "Produktová stránka — Business",
        "investing": "Investiční dokument",
        "insurance": "Pojištění",
    }
    if category in category_map:
        return category_map[category]

    if chunk_type:
        return f"Dokument — {chunk_type.replace('_', ' ').title()}"

    return "Dokument — RB"


def _build_display_url(url: str) -> str:
    """Shorten a URL for display (strip protocol, params, truncate)."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        # Show domain + meaningful path
        domain = parsed.netloc or parsed.hostname or "rb.cz"
        segments = path.split("/")
        # Keep last 2-3 meaningful segments
        meaningful = [s for s in segments if s and s not in (
            "cs", "en", "attachments", "documents", "files", "download",
        )]
        tail = "/".join(meaningful[-2:]) if meaningful else ""
        display = f"{domain}/{tail}" if tail else domain
        return display[:60]
    except Exception:
        return url[:60]


def _find_source_year(doc: Document) -> int | None:
    """Extract the most reliable year from document metadata."""
    md = doc.metadata

    # Direct date fields
    for field in ("date", "doc_date", "source_date", "year", "document_date"):
        val = md.get(field)
        if val:
            year = _extract_year(str(val))
            if year:
                return year

    # URL
    url = str(md.get("source_url") or md.get("url") or "")
    year = _extract_year(url)
    if year:
        return year

    # Title
    title = str(md.get("title") or "")
    year = _extract_year(title)
    if year:
        return year

    # Filename
    filename = str(md.get("file_name") or "")
    year = _extract_year(filename)
    if year:
        return year

    return None


def generate_why_this_source(doc: Document, query_profile: QueryProfile | None = None) -> str:
    """Produce a human-readable explanation of why this source was selected.

    Args:
        doc: The source document.
        query_profile: Optional query profile for context-aware explanations.

    Returns:
        A Czech-language sentence explaining why this source was retrieved.
    """
    md = doc.metadata
    url = str(md.get("source_url") or md.get("url") or "")
    title = str(md.get("title") or str(md.get("file_name") or ""))
    chunk_type = str(md.get("chunk_type") or "")
    category = str(md.get("category") or "")
    authority_tier = str(md.get("authority_tier") or "")
    is_archived = md.get("is_archived") or md.get("is_discontinued")

    parts: list[str] = []

    # Authority
    if authority_tier:
        tier_labels = {
            "product_page": "produktová stránka RB",
            "faq_support_page": "FAQ / podpora RB",
            "current_pricing": "aktuální ceník RB",
            "generic_page": "běžná stránka RB",
            "historical_pdf": "historický dokument",
            "migration_notice": "migrační oznámení",
            "archived_legal": "archivní právní dokument",
        }
        tier_name = tier_labels.get(authority_tier, authority_tier.replace("_", " "))
        parts.append(f"zdroj typu {tier_name}")

    # Content match
    if chunk_type:
        chunk_labels = {
            "pricing_row": "obsahuje konkrétní cenový údaj",
            "faq": "odpovídá na častý dotaz",
            "product_overview": "popisuje produkt",
            "table": "obsahuje strukturovaná data",
        }
        label = chunk_labels.get(chunk_type, f"typ {chunk_type}")
        parts.append(label)

    # Category and intent
    if query_profile:
        intent_labels = {
            "pricing": "poplatek / cena",
            "account_overview": "informace o účtu",
            "card_overview": "informace o kartě",
            "credit_card": "kreditní karta",
            "rb_key_overview": "RB Klíč / autorizace",
            "payment_overview": "platby / převody",
            "sepa_swift_overview": "zahraniční platby",
            "mortgage_overview": "hypotéka",
            "investment_overview": "investice",
        }
        matched_intents = [v for k, v in intent_labels.items() if k in query_profile.labels]
        if matched_intents:
            parts.append(f"odpovídá tématu {' / '.join(matched_intents[:3])}")

    if category:
        parts.append(f"kategorie {category}")

    # Freshness
    if is_archived:
        parts.append("archivní dokument — informace nemusí být aktuální")
    else:
        parts.append("aktuální dokument")

    if not parts:
        return "Zdroj byl vybrán na základě relevance k dotazu."

    return "Zdroj byl vybrán, protože " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Priority 4 — Retrieval Explainability
# ---------------------------------------------------------------------------

def _build_retrieval_reason(doc: Document, category: str) -> str | None:
    """Explain why this source was retrieved (not just ranked high)."""
    md = doc.metadata
    retrieval_reasons = md.get("retrieval_reasons") or []
    if retrieval_reasons:
        for reason in retrieval_reasons:
            if "no_unambiguous_current_pricing" in str(reason):
                return "Varovný dokument — neexistuje jednoznačný aktuální ceník"
            if "canonical" in str(reason).lower():
                return "Kanonický zdroj pro daný produkt"
            if "pricing_warning" in str(reason).lower():
                return "Upozornění na chybějící ceník"
        return retrieval_reasons[0] if isinstance(retrieval_reasons[0], str) else None

    if category == "pricing":
        return "Ceníkový dokument relevantní k dotazu"
    if category == "product_page":
        return "Produktová stránka odpovídající dotazu"
    if category == "faq_support":
        return "FAQ / podpora relevantní k dotazu"
    return "Vyhledáno na základě relevance"


def _build_authority_reason(doc: Document) -> str | None:
    """Explain why this source's authority level was assigned."""
    _, authority_tier, reasons = _classify_document_authority(doc)
    if reasons:
        # Clean up internal prefix for display
        clean = []
        for r in reasons:
            r = r.replace("authority=", "")
            clean.append(r)
        return "; ".join(clean[:2])
    return None


def normalize_source_metadata(doc: Document) -> dict[str, Any]:
    """Produce human-readable UX metadata for a source document.

    Returns a dict with keys:
      - human_title (str): cleaned, readable title
      - display_url (str): shortened URL for display
      - source_year (int | None): extracted year
      - current_or_archived (str): badge label ('Aktuální' | 'Archivní' | 'FAQ' | 'Ceník' atd.)
      - source_category (str): classification (product_page, faq_support, pricing, …)
      - source_label (str): short UX label
      - why_this_source (str): human-readable explanation
      - trust_score (float): overall trust score 0-1
      - authority_weight (float): document authority component
      - recency_weight (float): document recency component
      - stability_weight (float): document stability component
      - authority_tier (str): authority tier name
    """
    md = doc.metadata
    url = str(md.get("source_url") or md.get("url") or "")

    human_title = _build_human_title(doc)
    display_url = _build_display_url(url)
    source_year = _find_source_year(doc)
    source_category = _guess_source_category(doc)

    # Badge logic
    if source_category == "archived":
        current_or_archived = "Archivní"
    elif source_category == "faq_support":
        current_or_archived = "FAQ"
    elif source_category == "pricing":
        current_or_archived = "Ceník"
    elif source_category == "product_page":
        current_or_archived = "Aktuální"
    elif source_category == "legal":
        current_or_archived = "Podmínky"
    else:
        current_or_archived = "Dokument"

    source_label = _SOURCE_LABEL_MAP.get(source_category, "Dokument")

    # Priority 5: Source UX refinement — context label and relevance reason
    source_context_label = _build_source_context_label(doc, source_category)
    source_relevance_reason = _build_source_relevance_reason(doc, source_category)

    # Priority 2b: Trust scoring
    trust = compute_source_trust(doc)

    # Priority 1b: Freshness governance
    freshness = compute_source_freshness(doc)

    return {
        "human_title": human_title[:100],
        "display_url": display_url[:80],
        "source_year": source_year,
        "current_or_archived": current_or_archived,
        "source_category": source_category,
        "source_label": source_label,
        "source_context_label": source_context_label,
        "source_relevance_reason": source_relevance_reason,
        # Trust scoring (P2)
        "trust_score": trust["trust_score"],
        "authority_weight": trust["authority_weight"],
        "recency_weight": trust["recency_weight"],
        "stability_weight": trust["stability_weight"],
        "authority_tier": trust["authority_tier"],
        # Freshness governance (P1)
        "source_freshness_bucket": freshness["source_freshness_bucket"],
        "freshness_priority_score": freshness["freshness_priority_score"],
        "stale_source_suppressed": freshness["stale_source_suppressed"],
        "effective_date": freshness["effective_date"],
        "valid_from": freshness["valid_from"],
        "valid_to": freshness["valid_to"],
        "freshness_reason": freshness["freshness_reason"],
        # Retrieval explainability (P4)
        "retrieval_reason": _build_retrieval_reason(doc, source_category),
        "authority_reason": _build_authority_reason(doc),
    }


# ---------------------------------------------------------------------------
# Priority 2b — Source Trust Scoring
# ---------------------------------------------------------------------------

_TRUST_RECENCY_CURRENT_YEAR = 2026

# How many years back is still considered "current" for stability
_TRUST_STABILITY_YEARS_THRESHOLD = 2


def compute_source_trust(doc: Document) -> dict[str, Any]:
    """Compute trust scoring components for a source document.

    Returns a dict with:
      - trust_score (float): overall 0-1 trust score
      - authority_weight (float): authority tier → 0.0-1.0
      - recency_weight (float): how recent the document is → 0.0-1.0
      - stability_weight (float): how stable/established → 0.0-1.0
      - authority_tier (str): the authority tier name
    """
    md = doc.metadata
    authority_tier, _, _ = _classify_document_authority(doc)
    if not isinstance(authority_tier, str):
        authority_tier = str(authority_tier) if authority_tier is not None else ""
    base_authority = DOCUMENT_AUTHORITY_TIERS.get(authority_tier, 0.5)

    # Extract metadata strings early for all sub-computations
    url = str(md.get("source_url") or md.get("url") or "").lower()
    title = str(md.get("title") or "").lower()
    filename = str(md.get("file_name") or "").lower()
    chunk_type = str(md.get("chunk_type") or "").lower()
    doc_type = str(md.get("document_type") or "").lower()
    category = str(md.get("category") or "").lower()
    hay = " ".join([url, title, filename])

    # 1. Authority weight (0.0-1.0, normalized from existing tiers)
    authority_weight = base_authority

    # 2. Recency weight (0.0-1.0)
    source_year = _find_source_year(doc)
    if source_year is not None:
        age = _TRUST_RECENCY_CURRENT_YEAR - source_year
        if age <= 0:
            recency_weight = 1.0  # Current year or future
        elif age <= 1:
            recency_weight = 0.95  # Last year
        elif age <= 2:
            recency_weight = 0.85  # 2 years old
        elif age <= 3:
            recency_weight = 0.70  # 3 years old
        elif age <= 5:
            recency_weight = 0.50  # 3-5 years
        else:
            recency_weight = 0.20  # Very old
    else:
        # No year — infer from metadata
        if any(k in hay for k in _ARCHIVED_KEYWORDS):
            recency_weight = 0.15
        elif any(k in hay for k in _CURRENT_KEYWORDS):
            recency_weight = 0.80
        elif any(k in hay for k in _MIGRATION_KEYWORDS):
            recency_weight = 0.30
        else:
            recency_weight = 0.60  # Neutral — assume reasonably current

    # 3. Stability weight (0.0-1.0)
    if doc_type == "faq" or chunk_type == "faq" or category in ("support", "faq", "help"):
        stability_weight = 1.0
    elif doc_type == "pricing" or "cenik" in filename or "sazebnik" in filename:
        stability_weight = 0.90
    elif category in ("retail", "accounts", "cards", "payments", "mortgages", "investments"):
        stability_weight = 0.85
    elif "product_page" in authority_tier:
        stability_weight = 0.90
    elif "migration" in authority_tier:
        stability_weight = 0.15
    elif "archived" in authority_tier or "historical" in authority_tier:
        stability_weight = 0.10
    elif "faq_support" in authority_tier:
        stability_weight = 1.0
    else:
        stability_weight = 0.70

    # 4. Combined trust score (weighted average)
    trust_score = round(
        0.50 * authority_weight +
        0.25 * recency_weight +
        0.25 * stability_weight,
        4,
    )

    return {
        "trust_score": trust_score,
        "authority_weight": round(authority_weight, 4),
        "recency_weight": round(recency_weight, 4),
        "stability_weight": round(stability_weight, 4),
        "authority_tier": authority_tier,
    }


# ---------------------------------------------------------------------------
# Priority 1b — Source Freshness Governance
# ---------------------------------------------------------------------------

_FRESHNESS_CURRENT_YEAR = 2026


def compute_source_freshness(doc: Document) -> dict[str, Any]:
    """Compute source freshness bucket and priority score.

    Returns a dict with:
      - source_freshness_bucket (str): "current" | "recent" | "stale" | "archived"
      - freshness_priority_score (float): 0.0–1.0 priority for ranking
      - stale_source_suppressed (bool): whether source should be suppressed
      - effective_date (str | None): extracted effective date
      - valid_from (str | None): extraction of valid-from date if available
      - valid_to (str | None): extraction of valid-to date if available
      - freshness_reason (str): human-readable reason
    """
    md = doc.metadata
    source_year = _find_source_year(doc) or md.get("document_year")
    try:
        year_int = int(source_year) if source_year else None
    except (ValueError, TypeError):
        year_int = None

    url = str(md.get("source_url") or md.get("url") or "").lower()
    title = str(md.get("title") or "").lower()
    filename = str(md.get("file_name") or "").lower()
    hay = " ".join([url, title, filename])

    is_archived = bool(md.get("is_archived") or md.get("is_discontinued"))
    if not is_archived:
        is_archived = any(
            term in hay for term in _ARCHIVED_KEYWORDS
        ) or any(
            term in hay for term in ("již nenabízené", "jiz nenabizene", "discontinued", "staré produkty", "stare produkty")
        )

    is_migration = any(term in hay for term in _MIGRATION_KEYWORDS)

    # Determine bucket
    if is_archived or is_migration:
        bucket = "archived"
    elif year_int is not None:
        age = _FRESHNESS_CURRENT_YEAR - year_int
        if age <= 0:
            bucket = "current"
        elif age <= 2:
            bucket = "recent"
        elif age <= 5:
            bucket = "stale"
        else:
            bucket = "archived"
    else:
        # No year — guess from metadata
        if any(k in hay for k in _CURRENT_KEYWORDS):
            bucket = "recent"
        elif is_archived:
            bucket = "archived"
        else:
            bucket = "current"  # Neutral default

    # Freshness priority score (0.0–1.0, for ranking use)
    if bucket == "current":
        priority_score = 1.0
    elif bucket == "recent":
        priority_score = 0.7
    elif bucket == "stale":
        priority_score = 0.3
    else:  # archived
        priority_score = 0.1

    # Stale/stale suppression
    stale_source_suppressed = bucket in ("stale", "archived")

    # Human-readable reason
    freshness_reasons: list[str] = []
    if bucket == "current":
        freshness_reasons.append("aktuální zdroj")
    elif bucket == "recent":
        freshness_reasons.append("relativně recentní zdroj")
    elif bucket == "stale":
        freshness_reasons.append("zastaralý zdroj")
    else:
        freshness_reasons.append("archivní / migrační zdroj")

    if stale_source_suppressed:
        freshness_reasons.append("potlačen při konfliktu s aktuálním zdrojem")

    # Extract effective/valid dates from metadata
    effective_date = str(md.get("effective_date") or md.get("date") or "")
    valid_from = str(md.get("valid_from") or md.get("valid_from_date") or "")
    valid_to = str(md.get("valid_to") or md.get("valid_to_date") or "")

    return {
        "source_freshness_bucket": bucket,
        "freshness_priority_score": priority_score,
        "stale_source_suppressed": stale_source_suppressed,
        "effective_date": effective_date or None,
        "valid_from": valid_from or None,
        "valid_to": valid_to or None,
        "freshness_reason": " — ".join(freshness_reasons) if freshness_reasons else None,
    }


# ---------------------------------------------------------------------------
# Priority 2a — Source Normalization UX (continued)
# ---------------------------------------------------------------------------

def _build_source_context_label(doc: Document, category: str) -> str | None:
    """Build a short contextual label for the source (e.g. 'Sekce: Poplatky').

    Extracts useful context from chunk metadata without relying on FAQ lookup.
    """
    md = doc.metadata
    fee_type = str(md.get("fee_type") or "").strip()
    product_name = str(md.get("product_name") or "").strip()
    chunk_type = str(md.get("chunk_type") or "").strip()
    document_type = str(md.get("document_type") or "").strip()
    title = str(md.get("title") or "").strip()

    # Pricing context
    if category == "pricing" and fee_type and fee_type not in ("", "Upozornění"):
        return f"Položka: {fee_type[:60]}"

    # Product context
    if product_name and product_name not in ("Upozornění", "Upřesnění"):
        return f"Produkt: {product_name[:60]}"

    # Section from title
    if title and len(title) > 5 and not any(
        marker in title.lower() for marker in ("hash", "sha", "md5")
    ):
        return f"Sekce: {title[:60].replace('_', ' ').title()}"

    # Document type context
    if document_type and document_type != "unknown":
        return f"Typ: {document_type.replace('_', ' ').title()}"

    return None


def _build_source_relevance_reason(doc: Document, category: str) -> str | None:
    """Build a short human-readable explanation of why this source was selected.

    Based on source category and retrieval metadata (not LLM-generated).
    """
    md = doc.metadata
    retrieval_reasons = md.get("retrieval_reasons") or []

    # Check for specific retrieval reasons
    for reason in retrieval_reasons:
        if "no_unambiguous_current_pricing" in str(reason):
            return None  # Don't show relevance for warning docs
        if "canonical" in str(reason).lower():
            return "Hlavní zdroj pro daný produkt"
        if "overview" in str(reason).lower():
            return "Přehledová informace o produktu"

    # Category-based reasons
    if category == "pricing":
        return "Ceníková položka relevantní k dotazu"
    if category == "product_page":
        return "Oficiální stránka produktu"
    if category == "faq_support":
        return "FAQ odpovídající tématu dotazu"
    if category == "legal":
        return "Obchodní podmínky vztahující se k dotazu"
    if category == "archived":
        return "Archivní dokument — informace nemusí být aktuální"

    return None

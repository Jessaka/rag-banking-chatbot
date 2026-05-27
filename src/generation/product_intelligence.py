"""Lightweight product intelligence layer for the RB banking RAG chatbot.

Provides deterministic product metadata, fallback overview templates, domain
mapping, and graceful degradation support — without any external dataset,
embedding, or retrieval dependency.

All products map 1:1 to existing overview_direct strategies in chain.py and
are cross-referenced with the pricing retriever's canonical product labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Product capability flags
# ---------------------------------------------------------------------------

SUPPORTED_CAPABILITIES = frozenset({
    "vedeni",           # Account management / maintenance fee queries
    "platebni_styk",    # Payment processing
    "internetove_bankovnictvi",  # Online banking
    "karta",            # Card products
    "hypoteka",         # Mortgage / home loan
    "investice",        # Investment products
    "sporeni",          # Savings
    "pujcka",           # Loan
    "sepa_swift",       # SEPA / SWIFT payments
    "apple_google_pay", # Mobile payments
    "bezpecnost",       # Security / fraud
    "reklamace",        # Complaints / chargebacks
    "limity",           # Limits
    "rb_klic",          # RB Key (digital auth)
    "kreditni_karta",   # Credit card specific
    "debetni_karta",    # Debit card specific
})


# ---------------------------------------------------------------------------
# Product record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductInfo:
    """Immutable product metadata used for graceful degradation and overview."""
    product_id: str
    display_name: str
    domain: str
    short_description: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    overview_strategy: str = ""
    pricing_note: str = "Aktuální ceník závisí na variantě produktu — doporučujeme zkontrolovat detail v internetovém bankovnictví."
    cta_text: str = "Podrobnosti najdete v internetovém bankovnictví nebo na pobočce Raiffeisenbank."


# ---------------------------------------------------------------------------
# Master product registry
# ---------------------------------------------------------------------------

PRODUCT_REGISTRY: dict[str, ProductInfo] = {
    "ekonto_osobni": ProductInfo(
        product_id="ekonto_osobni",
        display_name="Osobní eKonto",
        domain="osobni_ucty",
        short_description="Osobní běžný účet pro každodenní bankovnictví s možností výběru tarifu.",
        capabilities=("vedeni", "platebni_styk", "internetove_bankovnictvi", "karta"),
        overview_strategy="account_overview_direct",
        pricing_note="Měsíční poplatek za vedení Osobního eKonta závisí na zvoleném tarifu (eKonto Smart, eKonto Komplet, eKonto Výhody). Doporučujeme zkontrolovat aktuální ceník v internetovém bankovnictví.",
    ),
    "ekonto_podnikatelske": ProductInfo(
        product_id="ekonto_podnikatelske",
        display_name="Podnikatelské eKonto",
        domain="podnikatele",
        short_description="Běžný účet pro podnikatele a živnostníky.",
        capabilities=("vedeni", "platebni_styk", "internetove_bankovnictvi", "karta"),
        overview_strategy="account_overview_direct",
    ),
    "aktivni_ucet": ProductInfo(
        product_id="aktivni_ucet",
        display_name="Aktivní účet",
        domain="osobni_ucty",
        short_description="Běžný účet s odměnou za aktivní využívání služeb.",
        capabilities=("vedeni", "platebni_styk", "internetove_bankovnictvi", "karta"),
        overview_strategy="account_overview_direct",
    ),
    "kreditni_karta": ProductInfo(
        product_id="kreditni_karta",
        display_name="Kreditní karta",
        domain="kreditni_karty",
        short_description="Kreditní karta s bezúročným obdobím a výhodným cestovním pojištěním.",
        capabilities=("karta", "kreditni_karta", "platebni_styk"),
        overview_strategy="card_overview_direct",
        pricing_note="Poplatek za vedení kreditní karty a úroková sazba závisí na konkrétním typu karty. Doporučujeme zkontrolovat přehled kreditních karet na rb.cz.",
    ),
    "hypoteky": ProductInfo(
        product_id="hypoteky",
        display_name="Hypotéka",
        domain="hypoteky",
        short_description="Hypoteční úvěr na bydlení s fixací úrokové sazby dle vašich potřeb.",
        capabilities=("hypoteka", "pujcka"),
        overview_strategy="mortgage_overview_direct",
        cta_text="Aktuální nabídku a sazby konzultujte s hypotečním specialistou na pobočce nebo na lince Raiffeisenbank.",
    ),
    "investice": ProductInfo(
        product_id="investice",
        display_name="Investiční produkty",
        domain="investice",
        short_description="Možnost investovat do podílových fondů, akcií a dalších instrumentů.",
        capabilities=("investice", "sporeni"),
        overview_strategy="investment_overview_direct",
        cta_text="Konkrétní informace o investičních produktech konzultujte s investičním specialistou.",
    ),
    "rb_klic": ProductInfo(
        product_id="rb_klic",
        display_name="RB Klíč",
        domain="rb_klic",
        short_description="Bezpečnostní autentizační nástroj pro přístup k internetovému bankovnictví.",
        capabilities=("rb_klic", "bezpecnost"),
        overview_strategy="rb_key_overview_direct",
    ),
    "sepa_swift": ProductInfo(
        product_id="sepa_swift",
        display_name="SEPA/SWIFT platby",
        domain="sepa_swift",
        short_description="Zahraniční platby v rámci EU (SEPA) i do ostatních zemí (SWIFT).",
        capabilities=("sepa_swift", "platebni_styk"),
        overview_strategy="sepa_swift_overview_direct",
    ),
    "apple_google_pay": ProductInfo(
        product_id="apple_google_pay",
        display_name="Apple Pay / Google Pay",
        domain="apple_google_pay",
        short_description="Placení mobilem přes Apple Pay a Google Pay.",
        capabilities=("apple_google_pay", "karta", "platebni_styk"),
        overview_strategy="card_overview_direct",
    ),
    "debetni_karta": ProductInfo(
        product_id="debetni_karta",
        display_name="Debetní karta",
        domain="cards",
        short_description="Platební karta k běžnému účtu pro výběry a platby.",
        capabilities=("karta", "debetni_karta", "platebni_styk"),
        overview_strategy="card_overview_direct",
    ),
    "pujcky": ProductInfo(
        product_id="pujcky",
        display_name="Půjčka / Úvěr",
        domain="pujcky",
        short_description="Spotřebitelský úvěr na cokoliv bez zástavy nemovitosti.",
        capabilities=("pujcka",),
        overview_strategy="product_overview_direct",
        pricing_note="Úroková sazba a měsíční splátka se odvíjí od výše úvěru a doby splácení. Doporučujeme využít online kalkulačku na rb.cz.",
    ),
    "sporeni": ProductInfo(
        product_id="sporeni",
        display_name="Spoření",
        domain="sporeni",
        short_description="Spořicí produkty včetně spořicího účtu a termínovaných vkladů.",
        capabilities=("sporeni",),
        overview_strategy="product_overview_direct",
    ),
}

# Map canonical product labels (from pricing_retriever) to product IDs
CANONICAL_TO_PRODUCT: dict[str, str] = {
    "osobni eKonto": "ekonto_osobni",
    "podnikatelske eKonto": "ekonto_podnikatelske",
    "kreditní karta": "kreditni_karta",
    "debetní karta": "debetni_karta",
    "hypotéku / nemovitost": "hypoteky",
    "hypoteka": "hypoteky",
    "půjčku / úvěr": "pujcky",
    "investice": "investice",
    "spoření": "sporeni",
    "SEPA/SWIFT platbu": "sepa_swift",
    "Apple Pay / Google Pay": "apple_google_pay",
    "RB Klíč": "rb_klic",
}


def get_product(product_id: str) -> ProductInfo | None:
    """Resolve a product by its canonical ID."""
    return PRODUCT_REGISTRY.get(product_id)


def find_product_by_canonical_label(label: str) -> ProductInfo | None:
    """Resolve a product from a pricing_retriever canonical product label."""
    pid = CANONICAL_TO_PRODUCT.get(label.lower())
    if pid:
        return PRODUCT_REGISTRY.get(pid)
    return None


def find_product_by_domain(domain: str) -> list[ProductInfo]:
    """Return all products in a given domain."""
    return [p for p in PRODUCT_REGISTRY.values() if p.domain == domain]


def generate_overview_fallback(product_id: str, question: str = "") -> str:
    """Generate a safe overview fallback answer for a product.

    This is used when pricing retrieval fails but the product is supported.
    No hallucinated pricing data — just product description + safe guidance.
    """
    product = get_product(product_id)
    if not product:
        return ""

    pricing_hint = "\n\n" + product.pricing_note if product.pricing_note else ""
    cta = "\n\n" + product.cta_text if product.cta_text else ""

    return (
        f"{product.display_name} je {product.short_description}"
        f"{pricing_hint}"
        f"{cta}"
    )

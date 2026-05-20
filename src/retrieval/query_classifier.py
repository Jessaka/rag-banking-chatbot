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


def classify_query(query: str) -> QueryProfile:
    q = query.lower()
    labels: set[str] = set()
    has_business_account_term = any(k in q for k in BUSINESS_ACCOUNT_TERMS)

    if any(k in q for k in ("poplatek", "poplatky", "cena", "stojí", "kolik", "sazebník", "ceník", "kč", "zdarma")):
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
    if any(k in q for k in ("karta", "karty", "limit karty", "kreditní", "debetní", "výběr", "bankomat")):
        labels.add("cards")
    if any(k in q for k in ("hypot", "úvěr na bydlení", "uver na bydleni")):
        labels.add("mortgages")
    if any(k in q for k in ("invest", "fond", "dip", "akcie", "dluhopis")):
        labels.add("investing")
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
    if "mortgages" in labels:
        preferred_categories.append("mortgages")
        preferred_urls.append("/hypotek")
    if "investing" in labels:
        preferred_categories.append("investments")
    if "insurance" in labels:
        preferred_categories.append("insurance")

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

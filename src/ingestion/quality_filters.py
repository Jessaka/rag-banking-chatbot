"""Quality filters for enterprise pricing row cleaning.

Detects and removes:
- OCR garbage (doubled chars, scrambled text, broken unicode)
- Header/table artifacts (Název položky, Sloupec X)
- Corrupted table rows (merged columns, dot noise, excess symbols)
- Invalid pricing fragments (missing product, missing fee_type)

Usage:
    from src.ingestion.quality_filters import filter_pricing_rows, PricingQualityStats

    filtered = filter_pricing_rows(all_rows)
    print(filtered.summary())  # garbage_rows, valid_rows, etc.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

MIN_FEE_TYPE_LENGTH = 3
MIN_PRODUCT_NAME_LENGTH = 3
MIN_VALID_TEXT_LENGTH = 10
MIN_ALPHA_RATIO = 0.40
MIN_ALNUM_RATIO = 0.55
MAX_SINGLE_CHAR_TOKEN_RATIO = 0.35
MAX_SYMBOL_RATIO = 0.20
MAX_NON_ASCII_RATIO = 0.15
MAX_REPEATED_BIGRAM_RATIO = 0.12
MIN_CONFIDENCE_SOFT = 0.70

# Known good Czech banking words (positive signal)
_CZECH_BANKING_WORDS = frozenset({
    "vedení", "poplatek", "cena", "tarifu", "účtu", "správa", "měsíčně", "měsíc",
    "zřízení", "platba", "karta", "vklad", "výběr", "příchozí", "odchozí",
    "expresní", "vnitrobankovní", "příplatek", "limit", "denní", "měsíční",
    "roční", "kreditní", "debetní", "mimořádný", "výměna", "blokace",
    "obnovení", "vydání", "služba", "produkt", "účet", "vložení", "výpis",
    "transakce", "zadání", "změna", "zrušení", "zdarma", "v ceně", "cena",
    "tarif", "sazba", "sazebník", "ceník", "položka", "poplatky",
    "bankovnictví", "internetové", "mobilní", "aplikace", "konto",
    "osobní", "firemní", "podnikatelské", "hypotéka", "půjčka", "úvěr",
    "spoření", "investice", "pojištění", "penze", "leasing",
})

# Header/table labels that should never appear as fee_type or product_name
_HEADER_LABELS = frozenset({
    "název položky", "název polozky", "nazev polozky", "nazev položky",
    "poplatek", "cena", "hodnota", "typ", "měna", "frekvence",
})

# Substrings that indicate a Sloupec X column header
_SLOUPEC_RE = re.compile(r"^sloupec\s+\d+", re.IGNORECASE)

# Doubled-character regex: 2+ consecutive same letter (like PPoojjii)
_DOUBLED_CHAR_RE = re.compile(r"([A-Za-zÁ-ž])\1+")

# Excessive dot-digit noise: "43..24.." or "111...654..."
_DOT_NOISE_RE = re.compile(r"\d{2,}\.\.\d", re.IGNORECASE)

# Broken unicode private use area / surrogate range
_BROKEN_UNICODE_RE = re.compile(r"[\ue000-\uf8ff]")

# Single-character token detection for scramble check
_SINGLE_CHAR_STRIP = ".,;:()[]{}|!?"

# Repeated punctuation like "...." or "!!!"
_REPEATED_PUNCT_RE = re.compile(r"([.,;:!?])\1{3,}")

# Valid pricing value regex (like "zdarma", "v ceně", "25 Kč", "0,5 %")
_VALID_VALUE_RE = re.compile(r"(zdarma|v ceně|[0-9]+[\s,.]*[0-9]*\s*(Kč|CZK|%))", re.IGNORECASE)

# Truncated text ending mid-word or mid-sentence
_TRUNCATED_END_RE = re.compile(r"(a\s*$|a\.\.$|\.\s*$|[a-z]\s*$)")

# Bad fee_type patterns
_BAD_FEE_RE = re.compile(
    r"^(název položky|nazev polozky|poplatek|cena|hodnota|typ|měna|frekvence|sloupec\s+\d+)$",
    re.IGNORECASE,
)

# Products that are actually "Sloupec X"
_SLOUPEC_PROD_RE = re.compile(r"^sloupec\s+\d+$", re.IGNORECASE)

# ─── Section blacklist ───────────────────────────────────────────────────────

SECTION_BLACKLIST_PREFIXES = (
    "/pro-media/", "/tiskove-zpravy/", "/tiskové-zprávy/",
    "/novinky/", "/kariera/", "/kariéra/",
    "/blog/", "/media/", "/attachments/kariera",
)
SECTION_BLACKLIST_KEYWORDS = (
    "tisková zpráva", "tiskova zprava", "pro média", "pro media",
    "novinka", "kariera", "kariéra", "blog", "press release",
    "media relations", "pro novináře", "pro novinare",
)

# ─── Navigation/noise chunk detection ────────────────────────────────────────

NAVIGATION_PATTERNS = (
    r"\b(menu|navigace|přihlášení|prihlaseni|registrace|kontakt|vyhledávání|vyhledavani)\b",
    r"\b(cookies|cookie\s*banner|gdpr|ochrana\s*osobních\s*údajů)\b",
    r"\b(přejít\s*na|zpět\s*na|zpět\s*do|nahoru|další\s*strana)\b",
    r"\b(sdílet|tweet|facebook|instagram|linkedin|youtube)\b",
)
_NAV_RE = re.compile("|".join(NAVIGATION_PATTERNS), re.IGNORECASE)

LOW_INFO_PATTERNS = (
    r"^\s*$",
    r"^\s*\d+\s*$",
    r"^\s*[\.,;:!?\-\s]+\s*$",
    r"^(loading|načítání|nactitani|prosím\s*čekejte)\b",
)
_LOW_INFO_RE = re.compile("|".join(LOW_INFO_PATTERNS), re.IGNORECASE)

# ─── Duplicate detection ────────────────────────────────────────────────────

_CONTENT_HASH_CACHE: dict[str, str] = {}


def content_signature(text: str) -> str:
    """Create a normalized signature for duplicate detection.

    Strips whitespace, lowercases, removes punctuation, sorts tokens.
    """
    import hashlib
    normalized = re.sub(r"[^a-z0-9áčďéěíňóřšťúůýž ]", "", text.lower())
    tokens = sorted(normalized.split())
    sig = " ".join(tokens)
    return hashlib.md5(sig.encode()).hexdigest()


def is_low_information(text: str) -> bool:
    """Detect chunks with minimal informational content.

    Returns True if text is empty, purely numeric, or contains only noise.
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()
    if len(stripped) < 20:
        return True
    # Pure numeric or punctuation
    if _LOW_INFO_RE.match(stripped):
        return True
    # Less than 3 alphabetic chars
    alpha = sum(c.isalpha() for c in stripped)
    if alpha < 10:
        return True
    return False


def is_navigation_chunk(text: str) -> bool:
    """Detect chunks that contain mostly navigation/UI boilerplate.

    Returns True if navigation signal is strong relative to content length.
    """
    if not text:
        return False
    # Count navigation matches
    matches = _NAV_RE.findall(text.lower())
    if not matches:
        return False
    # Check density: nav words vs total words
    words = len(text.split())
    if words < 10 and len(matches) >= 2:
        return True
    if words >= 10 and len(matches) / max(words, 1) > 0.3:
        return True
    return False


def is_garbage_chunk(text: str) -> bool:
    """Detect garbage chunks using the full quality filter suite.

    Combines OCR detection, low information, navigation, and alpha checks.
    """
    if is_low_information(text):
        return True
    if is_navigation_chunk(text):
        return True
    if is_garbage_text(text):
        return True
    # Additional chunk-specific: too much numeric noise
    digits = sum(c.isdigit() for c in text)
    if text and digits / max(len(text), 1) > 0.6:
        return True
    return False


def is_duplicate_chunk(text: str, existing_signatures: set[str] | None = None) -> bool:
    """Detect duplicate chunks by content signature.

    If existing_signatures is provided, checks against it and updates it.
    """
    sig = content_signature(text)
    if existing_signatures is not None:
        if sig in existing_signatures:
            return True
        existing_signatures.add(sig)
    return False


def score_chunk_quality(text: str) -> dict[str, float | bool | str]:
    """Score a chunk on multiple quality dimensions.

    Returns dict with:
      - quality_score: float 0.0–1.0
      - is_garbage: bool
      - is_navigation: bool
      - is_low_information: bool
      - is_duplicate: bool (requires external sig set)
      - ocr_noise_score: float 0.0–1.0
      - reasons: list[str]
    """
    reasons: list[str] = []
    score = 1.0

    li = is_low_information(text)
    if li:
        score -= 0.40
        reasons.append("low_information")

    nav = is_navigation_chunk(text)
    if nav:
        score -= 0.30
        reasons.append("navigation")

    gt = is_garbage_text(text)
    if gt:
        score -= 0.40
        reasons.append("garbage_text")

    # OCR noise score: continuous metric
    alpha = sum(c.isalpha() for c in text) if text else 0
    alpha_ratio = alpha / max(len(text), 1) if text else 0
    ocr_noise = max(0.0, 1.0 - (alpha_ratio / MIN_ALPHA_RATIO)) if alpha_ratio < MIN_ALPHA_RATIO else 0.0

    # Repeated char penalty
    repeated = _DOUBLED_CHAR_RE.findall(text)
    if len(repeated) >= 2:
        ocr_noise = min(1.0, ocr_noise + 0.15 * len(repeated))
        reasons.append("repeated_chars")

    # Scrambled text penalty
    if is_scrambled_text(text):
        ocr_noise = min(1.0, ocr_noise + 0.30)
        reasons.append("scrambled")

    score = max(0.0, min(1.0, score - ocr_noise * 0.3))

    return {
        "quality_score": round(score, 3),
        "is_garbage": score < 0.35 or gt,
        "is_navigation": nav,
        "is_low_information": li,
        "ocr_noise_score": round(ocr_noise, 3),
        "reasons": reasons,
    }


def is_blacklisted_section(url: str) -> bool:
    """Check if a URL belongs to a blacklisted section (media, blog, etc.)."""
    path = urlparse(url).path if "://" in url else url
    path_lower = path.lower()
    if any(path_lower.startswith(prefix) for prefix in SECTION_BLACKLIST_PREFIXES):
        return True
    if any(kw in path_lower for kw in SECTION_BLACKLIST_KEYWORDS):
        return True
    return False


# ─── Pricing-specific blacklist extensions ────────────────────────────────────

PRICING_BLACKLIST_WORDS = frozenset({
    "správa služby", "správa každé", "telefonní bankovnictví", "telefonni bankovnictvi",
    "informuj mě", "informuj me", "sms", "rb klíč", "rb klic",
    "notifikace", "multicurrency", "doplňkové služby", "doplnkove sluzby",
    "měnová složka", "menova slozka", "měnové složky", "menove slozky",
})


def is_pricing_blacklisted_row(row: dict[str, Any]) -> bool:
    """Check if pricing row should be excluded based on blacklist words.

    This catches rows that ARE valid pricing but should not appear
    in primary account fee queries (service fees, notification fees, etc.).
    """
    combined = (
        f"{row.get('fee_type', '')} {row.get('product_name', '')} "
        f"{row.get('conditions', '')}"
    ).lower()
    return any(bw in combined for bw in PRICING_BLACKLIST_WORDS)


@dataclass
class PricingQualityStats:
    """Statistics from a quality filtering pass."""

    total_input: int = 0
    valid_output: int = 0
    filtered_garbage_ocr: int = 0
    filtered_corrupted_chars: int = 0
    filtered_header_artifact: int = 0
    filtered_scrambled: int = 0
    filtered_dot_noise: int = 0
    filtered_broken_unicode: int = 0
    filtered_excessive_symbols: int = 0
    filtered_low_alpha: int = 0
    filtered_missing_fields: int = 0
    filtered_low_confidence: int = 0
    filtered_other: int = 0
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_filtered(self) -> int:
        return (
            self.filtered_garbage_ocr
            + self.filtered_corrupted_chars
            + self.filtered_header_artifact
            + self.filtered_scrambled
            + self.filtered_dot_noise
            + self.filtered_broken_unicode
            + self.filtered_excessive_symbols
            + self.filtered_low_alpha
            + self.filtered_missing_fields
            + self.filtered_low_confidence
            + self.filtered_other
        )

    def summary(self) -> str:
        return (
            f"PricingQualityStats: {self.total_input} → {self.valid_output} valid "
            f"({self.total_filtered} filtered: "
            f"header={self.filtered_header_artifact}, "
            f"corrupted_ocr={self.filtered_corrupted_chars}, "
            f"scrambled={self.filtered_scrambled}, "
            f"dot_noise={self.filtered_dot_noise}, "
            f"broken_unicode={self.filtered_broken_unicode}, "
            f"low_alpha={self.filtered_low_alpha}, "
            f"excessive_symbols={self.filtered_excessive_symbols}, "
            f"garbage_ocr={self.filtered_garbage_ocr}, "
            f"missing_fields={self.filtered_missing_fields}, "
            f"low_confidence={self.filtered_low_confidence}, "
            f"other={self.filtered_other})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input": self.total_input,
            "valid_output": self.valid_output,
            "total_filtered": self.total_filtered,
            "filtered_header_artifact": self.filtered_header_artifact,
            "filtered_corrupted_chars": self.filtered_corrupted_chars,
            "filtered_scrambled": self.filtered_scrambled,
            "filtered_dot_noise": self.filtered_dot_noise,
            "filtered_broken_unicode": self.filtered_broken_unicode,
            "filtered_low_alpha": self.filtered_low_alpha,
            "filtered_excessive_symbols": self.filtered_excessive_symbols,
            "filtered_garbage_ocr": self.filtered_garbage_ocr,
            "filtered_missing_fields": self.filtered_missing_fields,
            "filtered_low_confidence": self.filtered_low_confidence,
            "filtered_other": self.filtered_other,
        }


# ─── Individual quality checks ───────────────────────────────────────────────


def has_repeated_char_patterns(text: str) -> bool:
    """Detect doubled/trebled characters like PPoojjiiššttěěnníí.

    Looks for patterns where the same character appears 3+ times consecutively.
    At least 3 such occurrences indicates OCR doubling corruption.
    """
    if not text:
        return False
    matches = _DOUBLED_CHAR_RE.findall(text)
    return len(matches) >= 3


def has_corrupted_ocr(text: str) -> bool:
    """Detect general OCR corruption: entropy, spacing, single-char scattering.

    Looks for:
    - Single characters separated by spaces: "Z Z p r a c o v á n í"
    - Interleaved dots and text: "43..24.. ZZpprraaccoovváánníí"
    """
    if not text:
        return False
    # Pattern: single letter surrounded by spaces
    scattered = re.search(r"(?:\b\w\b\s+){4,}", text)
    if scattered:
        return True
    # Mixed dot sequences with letters
    if _DOT_NOISE_RE.search(text):
        return True
    # Repeated punctuation
    if _REPEATED_PUNCT_RE.search(text):
        return True
    return False


def has_low_alpha_ratio(text: str) -> bool:
    """Detect text with abnormally low alphabetic character ratio (< 0.40).

    OCR garbage often has a high proportion of digits, symbols, or noise.
    """
    if not text:
        return True
    alpha = sum(c.isalpha() for c in text)
    return alpha / max(len(text), 1) < MIN_ALPHA_RATIO


def has_broken_diacritics(text: str) -> bool:
    """Detect broken unicode diacritics or private-use-area characters.

    Valid Czech characters (ÁáČčĎďÉéĚěÍíŇňÓóŘřŠšŤťÚúŮůÝýŽž)
    are NOT flagged — only truly broken unicode is detected.
    """
    if not text:
        return False
    # Private use area unicode (e.g., \ue646) — always broken
    if _BROKEN_UNICODE_RE.search(text):
        return True
    # Count suspicious non-ASCII characters that are NOT valid Czech
    valid_czech = set("ÁáČčĎďÉéĚěÍíŇňÓóŘřŠšŤťÚúŮůÝýŽž")
    suspicious = sum(1 for c in text if ord(c) > 127 and c not in valid_czech)
    if text and suspicious / max(len(text), 1) > MAX_NON_ASCII_RATIO:
        return True
    return False


def has_excessive_symbol_noise(text: str) -> bool:
    """Detect text with excessive non-alphanumeric symbols.

    A high ratio of symbols (.,;:!?()-/ etc.) indicates table artifacts.
    """
    if not text:
        return True
    alnum_or_space = sum(c.isalnum() or c.isspace() for c in text)
    symbol_ratio = 1.0 - (alnum_or_space / max(len(text), 1))
    return symbol_ratio > MAX_SYMBOL_RATIO


def is_scrambled_text(text: str) -> bool:
    """Detect scrambled/corrupted text with many single-character tokens.

    Examples:
      "Pod K n2O ik0M a0 t PKe Lčl E s mT k ěé Ps LíečUnKěS o n"
      "CB ěEa ž n é Ú Sč tr tay n ma 3i m zo 1 0 t r if y a c e n o"
    """
    if not text:
        return False
    tokens = text.split()
    if len(tokens) < 5:
        return False
    single_char = sum(1 for t in tokens if len(t.strip(_SINGLE_CHAR_STRIP)) <= 1)
    return single_char / max(len(tokens), 1) > MAX_SINGLE_CHAR_TOKEN_RATIO


def is_garbage_text(text: str) -> bool:
    """High-level check: is this text pure OCR garbage?

    Uses multiple signals; returns True if sufficiently corrupted.
    Precision > recall: aims to never reject a valid row.
    """
    if not text or len(text.strip()) < MIN_VALID_TEXT_LENGTH:
        return True

    reasons = []
    if has_repeated_char_patterns(text):
        reasons.append("repeated_chars")
    if has_corrupted_ocr(text):
        reasons.append("corrupted_ocr")
    if has_low_alpha_ratio(text):
        reasons.append("low_alpha")
    if has_broken_diacritics(text):
        reasons.append("broken_diacritics")
    if has_excessive_symbol_noise(text):
        reasons.append("excessive_symbols")
    if is_scrambled_text(text):
        reasons.append("scrambled")

    # Precision > recall: require at least 2 signals OR one very strong signal
    if len(reasons) >= 2:
        return True
    # Single strong signal
    if "scrambled" in reasons:
        return True
    if "broken_diacritics" in reasons and "low_alpha" in reasons:
        return True
    # Repeated chars alone is sufficient if 5+ groups (e.g., PPoojjiiššttěěnníí)
    if "repeated_chars" in reasons:
        matches = _DOUBLED_CHAR_RE.findall(text)
        if len(matches) >= 5:
            return True
    return False


def _has_czech_banking_signal(text: str) -> float:
    """Return ratio of known Czech banking words in text (0.0–1.0).

    Higher values = stronger signal that text is valid banking content.
    """
    if not text:
        return 0.0
    tokens = set(re.findall(r"\w+", text.lower()))
    if not tokens:
        return 0.0
    matches = sum(1 for t in tokens if t in _CZECH_BANKING_WORDS)
    return matches / max(len(tokens), 1)


def _is_numeric_pricing_value(text: str) -> bool:
    """Check if text looks like a pricing value (e.g., '25 Kč', 'zdarma')."""
    return bool(_VALID_VALUE_RE.search(text))


_GENERIC_PRODUCT_LABELS_RE = re.compile(
    r"^(?:veden[ií]\s+(?:jednoho\s+)?b[eě][zž]n[eé]ho\s+[uú][cč]tu|"
    r"veden[ií]\s+[uú][cč]tu|cena\s+tarifu|poplatek|cena|hodnota|měsíčně|mesicne|ročně|rocne)$",
    re.IGNORECASE,
)


def _amount_from_value(text: str) -> str:
    if re.search(r"zdarma|v\s+ceně|v\s+cene", text or "", re.IGNORECASE):
        return "0"
    match = re.search(r"\d+(?:[\s.]\d{3})*(?:[,.]\d+)?", text or "")
    return match.group(0).replace(" ", "") if match else ""


def _currency_from_value(text: str) -> str:
    if re.search(r"kč|czk|zdarma|v\s+ceně|v\s+cene", text or "", re.IGNORECASE):
        return "CZK"
    if re.search(r"eur|€", text or "", re.IGNORECASE):
        return "EUR"
    return ""


def _period_from_row(row: dict[str, Any]) -> str:
    existing = (row.get("period") or "").strip()
    if existing:
        return existing
    text = " ".join(str(row.get(k) or "") for k in ("fee_value", "fee_type", "conditions"))
    match = re.search(r"měsíčně|mesicne|ročně|rocne|jednorázově|jednorazove|denně|denne", text, re.IGNORECASE)
    if match:
        return match.group(0)
    fee_norm = text.lower()
    if any(token in fee_norm for token in ("vedení", "vedeni", "cena tarifu", "měsíční", "mesicni")):
        return "měsíčně"
    return ""


def _is_orphan_or_generic_product(row: dict[str, Any]) -> bool:
    product = (row.get("product_name") or "").strip()
    fee_type = (row.get("fee_type") or "").strip()
    if not product:
        return True
    if _GENERIC_PRODUCT_LABELS_RE.match(product):
        return True
    if product.lower() == fee_type.lower():
        return True
    if product.lower().startswith("sloupec "):
        return True
    return False


# ─── Pricing row validation ──────────────────────────────────────────────────


def _is_header_artifact(row: dict[str, Any]) -> bool:
    """Detect table header rows that leaked into pricing data.

    Název položky / Sloupec X as fee_type or product_name.
    """
    fee = (row.get("fee_type") or "").strip().lower()
    prod = (row.get("product_name") or "").strip().lower()
    if _BAD_FEE_RE.match(fee):
        return True
    if _SLOUPEC_PROD_RE.match(prod):
        return True
    return False


def _has_missing_fields(row: dict[str, Any]) -> bool:
    """Check if a pricing row has required fields with meaningful content."""
    fee = (row.get("fee_type") or "").strip()
    prod = (row.get("product_name") or "").strip()
    if len(fee) < MIN_FEE_TYPE_LENGTH or len(prod) < MIN_PRODUCT_NAME_LENGTH:
        return True
    if not row.get("fee_value"):
        return True
    return False


def _is_merged_table_column(row: dict[str, Any]) -> bool:
    """Detect rows where two table columns got merged into one field.

    Heuristic: if fee_type contains a numeric value pattern OR
    if fee_type is very long (>100 chars), it's likely a merge artifact.
    """
    fee = (row.get("fee_type") or "").strip()
    prod = (row.get("product_name") or "").strip()
    # fee_type should not contain pricing values
    if _VALID_VALUE_RE.search(fee):
        return True
    # fee_type that is suspiciously long (merged columns)
    if len(fee) > 100:
        return True
    # product_name that is actually "Sloupec X"
    if _SLOUPEC_RE.match(prod):
        return True
    return False


def is_valid_pricing_row(row: dict[str, Any] | Any) -> tuple[bool, str | None]:
    """Validate a complete pricing row for quality.

    Returns (True, None) if valid, or (False, reason) if rejected.

    Hard reject reasons (must not index):
    - 'header_artifact' — Název položky / Sloupec X
    - 'missing_fields' — empty fee_type, product_name, or fee_value
    - 'garbage_text' — OCR garbage / scrambled / corrupted
    - 'merged_column' — merged table columns
    - 'broken_unicode' — broken unicode characters
    - 'low_alpha' — insufficient alphabetic content

    Soft reject reasons (low quality, log but can skip):
    - 'low_confidence' — confidence below 0.70
    """
    if hasattr(row, "__dataclass_fields__"):
        row = {
            "fee_type": getattr(row, "fee_type", ""),
            "product_name": getattr(row, "product_name", ""),
            "fee_value": getattr(row, "fee_value", ""),
            "currency": getattr(row, "currency", ""),
            "period": getattr(row, "period", ""),
            "confidence": getattr(row, "confidence", 0),
            "conditions": getattr(row, "conditions", ""),
        }
    elif not isinstance(row, dict):
        return False, "invalid_type"

    fee_type = (row.get("fee_type") or "").strip()
    product_name = (row.get("product_name") or "").strip()
    fee_value = (row.get("fee_value") or "").strip()
    amount = str(row.get("amount") or _amount_from_value(fee_value)).strip()
    currency = (row.get("currency") or _currency_from_value(fee_value)).strip()
    period = _period_from_row(row).strip()
    confidence = float(row.get("confidence") or 0)

    # ── Hard reject: header artifacts ────────────────────────────────────
    if _is_header_artifact(row):
        return False, "header_artifact"

    # ── Hard reject: missing fields ──────────────────────────────────────
    if _has_missing_fields(row):
        return False, "missing_fields"

    # ── Hard reject: merged table columns ────────────────────────────────
    if _is_merged_table_column(row):
        return False, "merged_column"

    combined_text = f"{fee_type} {product_name} {fee_value}"

    # ── Hard reject: broken unicode ──────────────────────────────────────
    if has_broken_diacritics(combined_text):
        return False, "broken_unicode"

    # ── Hard reject: garbage text on fee_type or product ─────────────────
    if is_garbage_text(fee_type) or (len(product_name) > 12 and is_garbage_text(product_name)):
        return False, "garbage_text"

    # ── Hard reject: pure garbage in combined text ───────────────────────
    if is_garbage_text(combined_text):
        return False, "garbage_text"

    # ── Hard reject: missing valid pricing value ─────────────────────────
    if not _is_numeric_pricing_value(fee_value):
        # Allow only if there's a strong Czech banking signal
        banking_signal = _has_czech_banking_signal(f"{fee_type} {product_name}")
        if banking_signal < 0.05:
            return False, "missing_pricing_value"

    # ── Soft reject: low confidence ──────────────────────────────────────
    if confidence < MIN_CONFIDENCE_SOFT:
        return False, "low_confidence"

    # ── Hard reject: orphan/generic product context ──────────────────────
    if _is_orphan_or_generic_product(row):
        return False, "orphan_product_context"

    # ── Hard reject: strict normalized schema fields ─────────────────────
    if not amount:
        return False, "missing_amount"
    if not currency:
        return False, "missing_currency"
    if not period:
        return False, "missing_period"

    return True, None


# ─── Batch filter ────────────────────────────────────────────────────────────


def filter_pricing_rows(rows: list[dict[str, Any] | Any]) -> tuple[list[Any], PricingQualityStats]:
    """Filter a list of pricing rows, returning (valid_rows, stats).

    Args:
        rows: List of pricing rows (dicts or PricingRow dataclass instances).

    Returns:
        Tuple of (filtered_valid_rows, PricingQualityStats).
    """
    stats = PricingQualityStats(total_input=len(rows))
    valid: list[Any] = []

    for row in rows:
        is_valid, reason = is_valid_pricing_row(row)
        if is_valid:
            valid.append(row)
            continue

        stats.rejected_rows.append({
            "reason": reason,
            "fee_type": str(getattr(row, "fee_type", row.get("fee_type", "")))[:60] if isinstance(row, (dict,)) else str(getattr(row, "fee_type", ""))[:60],
            "product_name": str(getattr(row, "product_name", row.get("product_name", "")))[:60] if isinstance(row, (dict,)) else str(getattr(row, "product_name", ""))[:60],
        })

        if reason == "garbage_text":
            stats.filtered_garbage_ocr += 1
        elif reason == "corrupted_chars":
            stats.filtered_corrupted_chars += 1
        elif reason == "header_artifact":
            stats.filtered_header_artifact += 1
        elif reason == "scrambled":
            stats.filtered_scrambled += 1
        elif reason == "dot_noise":
            stats.filtered_dot_noise += 1
        elif reason == "broken_unicode":
            stats.filtered_broken_unicode += 1
        elif reason == "excessive_symbols":
            stats.filtered_excessive_symbols += 1
        elif reason == "low_alpha":
            stats.filtered_low_alpha += 1
        elif reason == "missing_fields":
            stats.filtered_missing_fields += 1
        elif reason == "low_confidence":
            stats.filtered_low_confidence += 1
        elif reason in {"missing_pricing_value", "missing_amount", "missing_currency", "missing_period", "orphan_product_context"}:
            stats.filtered_missing_fields += 1
        elif reason == "merged_column":
            stats.filtered_garbage_ocr += 1
        else:
            stats.filtered_other += 1

    stats.valid_output = len(valid)
    return valid, stats


def filter_pricing_jsonl(
    input_path: Path,
    output_path: Path | None = None,
    rejected_output_path: Path | None = None,
) -> PricingQualityStats:
    """Filter an existing pricing_rows.jsonl file in-place or to a new path.

    Args:
        input_path: Path to input JSONL file.
        output_path: Path to output JSONL file. If None, overwrites input.

    Returns:
        PricingQualityStats with filtering results.
    """
    if not input_path.exists():
        logger.warning(f"Pricing rows file not found: {input_path}")
        return PricingQualityStats()

    rows: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    valid, stats = filter_pricing_rows(rows)
    output = output_path or input_path
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in valid:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    rejected_output = rejected_output_path or (output.parent / "pricing_rows_rejected.jsonl")
    if stats.rejected_rows:
        rejected_output.parent.mkdir(parents=True, exist_ok=True)
        with rejected_output.open("w", encoding="utf-8") as f:
            for row in stats.rejected_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info(f"Pricing rejected rows audit: {rejected_output} ({len(stats.rejected_rows)} rows)")

    logger.info(f"Pricing quality filter: {stats.summary()}")
    return stats


def filter_pricing_dataclass_rows(
    rows: list[Any],
) -> tuple[list[Any], PricingQualityStats]:
    """Filter PricingRow dataclass instances (from pricing_extractor).

    This converts to dict, filters, and converts back.
    """
    from dataclasses import asdict

    dicts = [asdict(r) for r in rows]
    valid_dicts, stats = filter_pricing_rows(dicts)

    # Reconstruct dataclass instances
    valid_rows: list[Any] = []
    original_by_key: dict[str, list[Any]] = {}
    for r in rows:
        key = (r.fee_type, r.product_name, r.fee_value)
        original_by_key.setdefault(key, []).append(r)

    for vd in valid_dicts:
        key = (vd["fee_type"], vd["product_name"], vd["fee_value"])
        candidates = original_by_key.get(key, [])
        if candidates:
            valid_rows.append(candidates[0])
        else:
            valid_rows.append(vd)  # fallback to dict

    return valid_rows, stats

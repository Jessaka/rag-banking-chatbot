"""Utility for lightweight URL‑based product filtering.

The function ``is_product_url`` implements the heuristic derived from the
URL‑structure audit. It operates solely on the URL (no title or content) and
does **not** require any index changes – it can be applied on‑the‑fly to the
list of candidate ``Document`` objects returned by the hybrid search.

The heuristic distinguishes *product* segments from *non‑product* segments.
If a URL contains at least one product segment and none of the non‑product
segments, the URL is considered a product page.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Heuristic keyword sets – derived from the audit (see implementation plan).
# ---------------------------------------------------------------------------
PRODUCT_SEGMENTS = {
    "kreditni-karty",
    "kreditni-karta",
    "kreditni",
    "karta",
    "ucty",
    "ucet",
    "hypoteky",
    "hypoteka",
    "financovani",
    "pujcka",
    "investicni-uver",
    "investicni",
    "investice",
    "fondy",
    "podilove-fondy",
    "sporeni",
    "produkty",
    "product",
}

NON_PRODUCT_SEGMENTS = {
    "podpora",
    "faq",
    "jak-",
    "formular",
    "zadost",
    "blokace",
    "prihlaseni",
    "informacni-servis",
    "aktuality",
    "attachments",
    "media",
    "povinne-zverejnovane-informace",
}

def _segment_path(url: str) -> list[str]:
    """Extract path segments from a URL, lower‑cased and without empty parts."""
    # Remove scheme and domain
    path = re.sub(r"^https?://[^/]+", "", url.lower())
    return [seg for seg in path.split('/') if seg]

def is_product_url(url: str) -> bool:
    """Return ``True`` if the URL looks like a product page.

    The decision is based on the presence of at least one *product* segment
    and the absence of any *non‑product* segment.
    """
    segs = _segment_path(url)
    has_product = any(any(p in seg for p in PRODUCT_SEGMENTS) for seg in segs)
    has_non = any(any(n in seg for n in NON_PRODUCT_SEGMENTS) for seg in segs)
    return has_product and not has_non

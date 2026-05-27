"""Source Governance Hardening Layer.

Provides hard suppression, canonical priority resolution, and document
lineage management for the RB banking RAG retrieval pipeline.

All policies are applied AFTER retrieval/rerank but BEFORE sources are
returned to the chain. This prevents outdated or non-preferred sources
from reaching the LLM even when their retrieval scores are high.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from langchain_core.documents import Document

from src.retrieval.query_classifier import (
    QueryProfile,
    _classify_document_authority,
    _find_source_year,
    compute_source_freshness,
    is_archived_doc,
)

# ---------------------------------------------------------------------------
# Retrieval Recovery & Resilience defaults
# ---------------------------------------------------------------------------

MIN_REQUIRED_DOCS = 3
RECOVERY_SUPPRESSION_THRESHOLD = 0.50
MAX_RECOVERY_DOCS = 2
MAX_CHUNKS_PER_DOCUMENT = 2
MAX_CHUNKS_PER_FAMILY = 3

# ---------------------------------------------------------------------------
# Canonical source hierarchy (P2)
# Lower number = higher priority
# ---------------------------------------------------------------------------

CANONICAL_PRIORITY_ORDER: dict[str, int] = {
    "product_page": 1,        # Current product page — highest authority
    "current_pricing": 2,     # Current pricing PDF
    "faq_support_page": 3,    # Current FAQ / support
    "current_pdf": 4,         # Current non-pricing PDF (legal, terms)
    "generic_page": 5,        # Generic web page
    "recent_page": 6,         # Recent but not current
    "historical_pdf": 7,      # Historical / out-of-date
    "migration_notice": 8,    # Migration / change notice
    "archived_legal": 9,      # Archived legal-only
    "unknown": 10,            # Unknown / fallback
}

# Source types that are considered "current" for the same-type competition rule
_CURRENT_SOURCE_TYPES = frozenset({
    "product_page",
    "current_pricing",
    "faq_support_page",
    "current_pdf",
})

# Source types that are NEVER allowed as primary (highest-ranked) answer sources
_PRIMARY_BLOCKED_TYPES = frozenset({
    "migration_notice",
    "archived_legal",
    "historical_pdf",
})


# ---------------------------------------------------------------------------
# P1 — Hard Source Suppression
# ---------------------------------------------------------------------------

def apply_source_suppression(
    docs: list[Document],
    query_profile: QueryProfile | None = None,
) -> tuple[list[Document], list[dict[str, Any]]]:
    """Apply hard suppression rules to a list of retrieved documents.

    Rules:
      1. Archived source NEVER beats a current source of the same type.
      2. Historical pricing blocked if current pricing exists.
      3. Migration notices NEVER primary source.
      4. Deprecated FAQ NEVER primary source.

    The filter removes suppressed documents and attaches suppression
    metadata to the remaining ones.

    Args:
        docs: Retrieved and ranked documents.
        query_profile: Optional query profile for context.

    Returns:
        (filtered_docs, suppression_log) — filtered docs and a list of
        suppression events with reasons.
    """
    if not docs:
        return docs, []

    suppression_log: list[dict[str, Any]] = []
    kept: list[Document] = []
    suppressed_keys: set[str] = set()

    # Categorize docs by canonical type
    docs_by_type: dict[str, list[tuple[int, Document]]] = defaultdict(list)
    for idx, doc in enumerate(docs):
        tier, _, _ = _classify_document_authority(doc)
        docs_by_type[tier].append((idx, doc))

    # Rule 1: Archived source NEVER beats current source of same type
    for tier in _CURRENT_SOURCE_TYPES:
        current_docs = docs_by_type.get(tier, [])
        if not current_docs:
            continue
        # Check if any current exists; if so, suppress archived variants
        for other_tier in ("archived_legal", "historical_pdf"):
            for idx, doc in docs_by_type.get(other_tier, []):
                if _same_source_family(doc, current_docs[0][1]):
                    suppressed_keys.add(idx)
                    suppression_log.append({
                        "rule": "archived_not_beats_current",
                        "suppressed_idx": idx,
                        "suppressed_tier": other_tier,
                        "current_tier": tier,
                        "suppression_reason": f"Archived source ({other_tier}) suppressed — current {tier} exists for the same document family.",
                    })

    # Rule 2: Historical pricing blocked if current pricing exists
    if "current_pricing" in docs_by_type and "historical_pdf" in docs_by_type:
        for idx, doc in docs_by_type["historical_pdf"]:
            # Only suppress historical pricing docs
            if doc.metadata.get("document_type") == "pricing" or "pricing" in str(doc.metadata.get("category", "")).lower():
                # Check if it's the same pricing document family
                for _, current_doc in docs_by_type["current_pricing"]:
                    if _same_pricing_family(doc, current_doc):
                        suppressed_keys.add(idx)
                        suppression_log.append({
                            "rule": "historical_pricing_blocked",
                            "suppressed_idx": idx,
                            "current_tier": "current_pricing",
                            "suppression_reason": "Historical pricing blocked — current pricing exists for the same product.",
                        })
                        break

    # Rule 3: Migration notices NEVER primary source
    # (They're allowed as secondary/context, but not as the top result)
    if "migration_notice" in docs_by_type:
        for idx, doc in docs_by_type["migration_notice"]:
            if idx == 0:  # Would be primary
                suppressed_keys.add(idx)
                suppression_log.append({
                    "rule": "migration_notice_not_primary",
                    "suppressed_idx": idx,
                    "suppression_reason": "Migration notice suppressed — never used as primary answer source.",
                })

    # Rule 4: Archived legal NEVER primary source
    if "archived_legal" in docs_by_type:
        for idx, doc in docs_by_type["archived_legal"]:
            if idx == 0:
                suppressed_keys.add(idx)
                suppression_log.append({
                    "rule": "archived_legal_not_primary",
                    "suppressed_idx": idx,
                    "suppression_reason": "Archived legal document suppressed — never used as primary answer source.",
                })

    # Rule 5: Deprecated FAQ not primary
    for idx, doc in enumerate(docs):
        if idx in suppressed_keys:
            continue
        tier, _, _ = _classify_document_authority(doc)
        if tier == "faq_support_page" and is_archived_doc(doc):
            suppressed_keys.add(idx)
            suppression_log.append({
                "rule": "deprecated_faq_not_primary",
                "suppressed_idx": idx,
                "suppression_reason": "Deprecated/archived FAQ suppressed — not used as primary source.",
            })

    # Build filtered list, attaching suppression metadata
    for idx, doc in enumerate(docs):
        if idx in suppressed_keys:
            doc.metadata["suppression_applied"] = True
            doc.metadata["stale_source_suppressed"] = True
            doc.metadata["suppression_reason"] = next(
                (s["suppression_reason"] for s in suppression_log if s["suppressed_idx"] == idx),
                "Suppressed by governance policy",
            )
        else:
            doc.metadata["suppression_applied"] = False
            doc.metadata["suppression_reason"] = None
            kept.append(doc)

    return kept, suppression_log


# ---------------------------------------------------------------------------
# P2 — Canonical Source Priority
# ---------------------------------------------------------------------------

def resolve_canonical_priority(docs: list[Document]) -> list[Document]:
    """Resolve canonical source hierarchy and attach canonical priority scores.

    Each doc gets:
      - canonical_priority (int): lower = higher priority
      - canonical_source_type (str): the matched canonical tier
      - canonical_override_used (bool): whether this source was promoted
        over a higher-similarity but lower-priority source

    Args:
        docs: Documents already ranked by retrieval/rerank score.

    Returns:
        Documents with canonical priority metadata attached, re-ranked
        by canonical priority as a tiebreaker.
    """
    if not docs:
        return docs

    # Attach canonical priority
    for doc in docs:
        tier, _, _ = _classify_document_authority(doc)
        priority = CANONICAL_PRIORITY_ORDER.get(tier, 10)
        doc.metadata["canonical_priority"] = priority
        doc.metadata["canonical_source_type"] = tier

    # Track overrides: a doc that is ranked lower by retrieval score
    # but has higher canonical priority
    if len(docs) > 1:
        top_priority = docs[0].metadata.get("canonical_priority", 10)
        for doc in docs[1:]:
            doc_priority = doc.metadata.get("canonical_priority", 10)
            doc.metadata["canonical_override_used"] = doc_priority < top_priority

        docs[0].metadata["canonical_override_used"] = False

    # Re-rank: stable sort preserving retrieval order within same priority
    docs.sort(key=lambda d: d.metadata.get("canonical_priority", 10))

    return docs


# ---------------------------------------------------------------------------
# P3 — Document Lineage Resolution
# ---------------------------------------------------------------------------

def resolve_document_lineage(docs: list[Document]) -> list[Document]:
    """Resolve document lineage — prefer newest active lineage member.

    Checks for:
      - supersedes_document (str): this doc replaces an older one
      - superseded_by (str): this doc has been replaced
      - document_generation (int): generation number (higher = newer)
      - document_version (str): version string
      - document_family (str): family identifier for grouping

    Rules:
      - If two docs share the same document_family, prefer the one with
        the higher document_generation.
      - A doc with superseded_by set is demoted unless it's the only
        member of its family.

    Args:
        docs: Documents to resolve lineage for.

    Returns:
        Documents with lineage metadata attached, filtered to prefer
        newest lineage members.
    """
    if not docs:
        return docs

    # Group by document family
    families: dict[str, list[tuple[int, Document]]] = defaultdict(list)
    for idx, doc in enumerate(docs):
        family = str(doc.metadata.get("document_family") or doc.metadata.get("file_name") or "").strip()
        if not family:
            family = f"_ungrouped_{idx}"
        families[family].append((idx, doc))

    kept: set[int] = set()
    lineage_log: list[dict[str, Any]] = []
    suppressed: set[int] = set()

    for family, members in families.items():
        if len(members) <= 1:
            kept.add(members[0][0])
            continue

        # Sort by generation (descending) — prefer newest
        members.sort(
            key=lambda m: (
                -int(m[1].metadata.get("document_generation", 0)),
                -(_find_source_year(m[1]) or 0),
            ),
        )

        # Check if top member has been superseded
        top_gen = members[0][1].metadata.get("document_generation", 0)
        top_year = _find_source_year(members[0][1]) or 0

        best_idx = members[0][0]
        for idx, doc in members:
            superseded_by = doc.metadata.get("superseded_by")
            if superseded_by and int(doc.metadata.get("document_generation", 0)) < top_gen:
                suppressed.add(idx)
                lineage_log.append({
                    "family": family,
                    "superseded": idx,
                    "superseded_by": superseded_by,
                    "lineage_reason": f"Document superseded by newer generation (gen {top_gen}).",
                })

        kept.add(best_idx)

    # Attach lineage metadata
    for idx, doc in enumerate(docs):
        if idx in suppressed:
            doc.metadata["suppression_applied"] = True
            doc.metadata["lineage_superseded"] = True
            doc.metadata["suppression_reason"] = next(
                (s["lineage_reason"] for s in lineage_log if s.get("superseded") == idx),
                "Superseded by newer document version.",
            )

    # If any lineage-based suppression happened, rebuild kept list
    if suppressed:
        for idx in suppressed:
            if idx in kept:
                kept.remove(idx)

    filtered = [doc for idx, doc in enumerate(docs) if idx in kept]

    return filtered if filtered else docs  # Never return empty if we had docs


# ---------------------------------------------------------------------------
# Orchestrated governance pipeline
# ---------------------------------------------------------------------------

def apply_governance_pipeline(
    docs: list[Document],
    query_profile: QueryProfile | None = None,
) -> tuple[list[Document], dict[str, Any]]:
    """Run the full source governance pipeline.

    Order:
      1. Source suppression (P1) — hard filter
      2. Document lineage (P3) — prefer newest
      3. Canonical priority (P2) — hierarchy re-rank

    Args:
        docs: Retrieved and ranked documents.
        query_profile: Optional query profile.

    Returns:
        (governed_docs, governance_meta) — filtered/re-ranked docs and
        governance metadata for debug/explainability.
    """
    governance_meta: dict[str, Any] = {
        "suppression_log": [],
        "lineage_log": [],
        "canonical_overrides": [],
        "input_count": len(docs),
        "output_count": 0,
        "min_required_docs": MIN_REQUIRED_DOCS,
        "suppressed_count": 0,
        "governance_removed_count": 0,
        "suppression_ratio": 0.0,
        "recovery_pass_used": False,
        "recovery_reason": None,
        "recovery_query": None,
        "recovery_result_count": 0,
        "retrieval_collapse_detected": False,
        "resilience_strategy": "normal_retrieval",
        "final_source_count": 0,
    }

    if not docs:
        return docs, governance_meta

    # Step 1: Hard suppression
    original_docs = list(docs)
    docs, suppression_log = apply_source_suppression(docs, query_profile)
    governance_meta["suppression_log"] = suppression_log
    suppressed_indices = {
        int(item["suppressed_idx"])
        for item in suppression_log
        if item.get("suppressed_idx") is not None
    }
    governance_meta["suppressed_count"] = len(suppressed_indices)
    governance_meta["governance_removed_count"] = len(original_docs) - len(docs)
    governance_meta["suppression_ratio"] = round(len(suppressed_indices) / max(1, len(original_docs)), 4)

    # Step 2: Lineage resolution
    docs = resolve_document_lineage(docs)

    # Step 3: Canonical priority
    docs = resolve_canonical_priority(docs)

    # Step 4: Resilience categories and collapse detection
    docs, category_meta = ensure_resilience_categories(docs)
    governance_meta.update(category_meta)
    recovery_meta = should_trigger_recovery(original_docs, docs, suppression_log)
    governance_meta.update(recovery_meta)

    # Step 5: Source diversity caps (post-governance anti-collapse guardrail)
    docs, diversity_meta = apply_source_diversity(docs)
    governance_meta.update(diversity_meta)

    governance_meta["output_count"] = len(docs)
    governance_meta["governance_applied"] = len(suppression_log) > 0
    governance_meta["final_source_count"] = len(docs)
    governance_meta["retrieval_collapse_detected"] = bool(
        governance_meta.get("retrieval_collapse_detected") or len(docs) < MIN_REQUIRED_DOCS
    )
    governance_meta["resilience_strategy"] = _resilience_strategy(governance_meta)

    attach_governance_summary(docs, governance_meta)

    return docs, governance_meta


# ---------------------------------------------------------------------------
# Retrieval Recovery & Resilience helpers
# ---------------------------------------------------------------------------

def should_trigger_recovery(
    original_docs: list[Document],
    current_docs: list[Document],
    suppression_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return recovery trigger metadata after governance suppression.

    Recovery is intentionally triggered by collapse indicators only; the
    actual recovery retrieval pass is orchestrated by the retriever using this
    metadata, so this module remains pure and unit-testable.
    """
    suppressed_indices = {
        int(item["suppressed_idx"])
        for item in suppression_log
        if item.get("suppressed_idx") is not None
    }
    input_count = len(original_docs)
    suppression_ratio = len(suppressed_indices) / max(1, input_count)
    reasons: list[str] = []
    if input_count and suppression_ratio > RECOVERY_SUPPRESSION_THRESHOLD:
        reasons.append("governance_suppression_ratio")
    if len(current_docs) < MIN_REQUIRED_DOCS:
        reasons.append("below_min_required_docs")
    triggered = bool(reasons)
    return {
        "recovery_pass_needed": triggered,
        "recovery_reason": ",".join(reasons) if reasons else None,
        "recovery_reasons": reasons,
        "retrieval_collapse_detected": triggered,
        "suppression_ratio": round(suppression_ratio, 4),
    }


def ensure_resilience_categories(docs: list[Document]) -> tuple[list[Document], dict[str, Any]]:
    """Attach normalized resilience categories to retrieved docs."""
    empty_category_count = 0
    derived_category_count = 0
    for doc in docs:
        source_key = "category"
        category = str(doc.metadata.get("category") or "").strip()
        if not category:
            empty_category_count += 1
            tier, _, _ = _classify_document_authority(doc)
            for key in ("document_type", "chunk_type", "canonical_source_type", "authority_tier"):
                value = str(doc.metadata.get(key) or "").strip()
                if value:
                    category = value
                    source_key = key
                    break
            if not category:
                category = tier or "unknown"
                source_key = "authority_classifier"
            derived_category_count += 1
        doc.metadata["resilience_category"] = category
        doc.metadata["resilience_category_derived"] = source_key != "category"
        doc.metadata["resilience_category_source"] = source_key
    return docs, {
        "empty_category_count": empty_category_count,
        "derived_category_count": derived_category_count,
    }


def compute_diversity_score(docs: list[Document]) -> float:
    """Compute a 0..1 source diversity score for final retrieval docs."""
    if not docs:
        return 0.0
    document_keys = {_document_key(doc) for doc in docs if _document_key(doc)}
    family_keys = {_family_key(doc) for doc in docs if _family_key(doc)}
    doc_ratio = len(document_keys) / max(1, len(docs))
    family_ratio = len(family_keys) / max(1, len(docs))
    return round(min(1.0, max(0.0, (doc_ratio + family_ratio) / 2)), 4)


def apply_source_diversity(
    docs: list[Document],
    *,
    max_chunks_per_document: int = MAX_CHUNKS_PER_DOCUMENT,
    max_chunks_per_family: int = MAX_CHUNKS_PER_FAMILY,
    min_required_docs: int = MIN_REQUIRED_DOCS,
) -> tuple[list[Document], dict[str, Any]]:
    """Apply post-governance source diversity caps without causing collapse."""
    if not docs:
        return docs, {
            "diversity_score": 0.0,
            "source_diversity_score": 0.0,
            "diversity_input_count": 0,
            "diversity_output_count": 0,
            "diversity_skipped_count": 0,
            "diversity_override_used": False,
            "max_chunks_per_document": max_chunks_per_document,
            "max_chunks_per_family": max_chunks_per_family,
        }

    document_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    kept: list[Document] = []
    skipped = 0
    override_used = False

    for doc in docs:
        doc_key = _document_key(doc)
        family_key = _family_key(doc)
        would_exceed_doc = doc_key and document_counts[doc_key] >= max_chunks_per_document
        would_exceed_family = family_key and family_counts[family_key] >= max_chunks_per_family
        if (would_exceed_doc or would_exceed_family) and len(kept) >= min_required_docs:
            skipped += 1
            override_used = True
            doc.metadata["diversity_override_used"] = True
            continue
        if would_exceed_doc or would_exceed_family:
            # Preserve recall above diversity when dropping would collapse output.
            override_used = True
        kept.append(doc)
        if doc_key:
            document_counts[doc_key] += 1
        if family_key:
            family_counts[family_key] += 1

    diversity_score = compute_diversity_score(kept)
    for doc in kept:
        doc.metadata["diversity_document_key"] = _document_key(doc)
        doc.metadata["diversity_family_key"] = _family_key(doc)
        doc.metadata["diversity_score"] = diversity_score
        doc.metadata["source_diversity_score"] = diversity_score
        doc.metadata["diversity_override_used"] = override_used
        doc.metadata["max_chunks_per_document"] = max_chunks_per_document
        doc.metadata["max_chunks_per_family"] = max_chunks_per_family

    return kept, {
        "diversity_score": diversity_score,
        "source_diversity_score": diversity_score,
        "diversity_input_count": len(docs),
        "diversity_output_count": len(kept),
        "diversity_skipped_count": skipped,
        "diversity_override_used": override_used,
        "max_chunks_per_document": max_chunks_per_document,
        "max_chunks_per_family": max_chunks_per_family,
    }


def attach_governance_summary(docs: list[Document], meta: dict[str, Any]) -> list[Document]:
    """Attach governance/recovery/diversity summary fields to all docs."""
    summary_fields = {
        "governance_removed_count": meta.get("governance_removed_count", 0),
        "governance_suppressed_count": meta.get("suppressed_count", 0),
        "suppression_ratio": meta.get("suppression_ratio", 0.0),
        "recovery_pass_used": meta.get("recovery_pass_used", False),
        "recovery_reason": meta.get("recovery_reason"),
        "recovery_query": meta.get("recovery_query"),
        "recovery_result_count": meta.get("recovery_result_count", 0),
        "recovery_pass_latency_ms": meta.get("recovery_pass_latency_ms", 0.0),
        "retrieval_collapse_detected": meta.get("retrieval_collapse_detected", False),
        "resilience_strategy": meta.get("resilience_strategy", "normal_retrieval"),
        "final_source_count": meta.get("final_source_count", len(docs)),
        "diversity_score": meta.get("diversity_score", 0.0),
        "source_diversity_score": meta.get("source_diversity_score", meta.get("diversity_score", 0.0)),
        "max_chunks_per_document": meta.get("max_chunks_per_document", MAX_CHUNKS_PER_DOCUMENT),
        "max_chunks_per_family": meta.get("max_chunks_per_family", MAX_CHUNKS_PER_FAMILY),
        "diversity_override_used": meta.get("diversity_override_used", False),
        "empty_category_count": meta.get("empty_category_count", 0),
        "derived_category_count": meta.get("derived_category_count", 0),
    }
    for doc in docs:
        doc.metadata.update(summary_fields)
    return docs


def merge_recovery_docs(
    current_docs: list[Document],
    recovery_docs: list[Document],
    *,
    recovery_reason: str,
    recovery_query: str,
    max_recovery_docs: int = MAX_RECOVERY_DOCS,
) -> tuple[list[Document], int]:
    """Append safe, non-duplicate recovery docs as secondary context."""
    seen_keys = {_chunk_key(doc) for doc in current_docs}
    merged = list(current_docs)
    added = 0
    for doc in recovery_docs:
        key = _chunk_key(doc)
        if key in seen_keys:
            continue
        tier = doc.metadata.get("canonical_source_type") or _classify_document_authority(doc)[0]
        if tier in _PRIMARY_BLOCKED_TYPES and not current_docs:
            continue
        doc.metadata.update({
            "recovery_pass_used": True,
            "recovery_applied": True,
            "recovery_reason": recovery_reason,
            "recovery_query": recovery_query,
            "recovery_rank": "secondary",
            "recovery_position": added + 1,
        })
        merged.append(doc)
        seen_keys.add(key)
        added += 1
        if added >= max_recovery_docs:
            break
    return merged, added


def _resilience_strategy(meta: dict[str, Any]) -> str:
    if meta.get("recovery_pass_used"):
        return "governance_recovery"
    if meta.get("retrieval_collapse_detected"):
        return "collapse_detected_no_recovery"
    if meta.get("diversity_override_used"):
        return "source_diversity_enforced"
    if meta.get("suppressed_count", 0) > 0:
        return "governance_suppressed"
    return "normal_retrieval"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SAME_SOURCE_METADATA_KEYS = ("file_name", "source_url", "url", "title", "document_family")


def _chunk_key(doc: Document) -> str:
    return str(
        doc.metadata.get("chunk_id")
        or doc.metadata.get("id")
        or doc.metadata.get("source_id")
        or f"{_document_key(doc)}::{doc.page_content[:120]}"
    )


def _document_key(doc: Document) -> str:
    return str(
        doc.metadata.get("source_url")
        or doc.metadata.get("url")
        or doc.metadata.get("file_name")
        or doc.metadata.get("source_file")
        or doc.metadata.get("source")
        or ""
    ).strip().lower()


def _family_key(doc: Document) -> str:
    return str(
        doc.metadata.get("document_family")
        or doc.metadata.get("canonical_product")
        or doc.metadata.get("product_name")
        or doc.metadata.get("source_url")
        or doc.metadata.get("url")
        or doc.metadata.get("file_name")
        or ""
    ).strip().lower()


def _same_source_family(doc_a: Document, doc_b: Document) -> bool:
    """Check if two documents belong to the same source family."""
    for key in _SAME_SOURCE_METADATA_KEYS:
        val_a = str(doc_a.metadata.get(key) or "").strip().lower()
        val_b = str(doc_b.metadata.get(key) or "").strip().lower()
        if val_a and val_b and (val_a == val_b or val_a in val_b or val_b in val_a):
            return True
    return False


def _same_pricing_family(doc_a: Document, doc_b: Document) -> bool:
    """Check if two pricing docs cover the same product."""
    prod_a = str(doc_a.metadata.get("product_name") or doc_a.metadata.get("canonical_product") or "").strip().lower()
    prod_b = str(doc_b.metadata.get("product_name") or doc_b.metadata.get("canonical_product") or "").strip().lower()
    if prod_a and prod_b and (prod_a == prod_b or prod_a in prod_b or prod_b in prod_a):
        return True
    # Fall back to file name comparison
    return _same_source_family(doc_a, doc_b)

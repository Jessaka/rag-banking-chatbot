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


def _score_row(row: dict, query: str, profile: QueryProfile) -> tuple[float, list[str]]:
    q_norm = _norm(expand_query(query, profile))
    text = _norm(_row_text(row))
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
    if any(k in q_norm for k in ("vedeni", "ucet", "uctu")) and any(k in text for k in ("vedeni", "cena", "poplatek", "ucet")):
        score += 0.6; reasons.append("account fee intent")
    if "vedeni" in q_norm and not any(k in _norm(str(row.get("fee_type") or "")) for k in ("vedeni", "cena", "poplatek")):
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


def pricing_search(query: str, top_k: int = 5, min_score: float = 0.5) -> list[Document]:
    profile = classify_query(query)
    if "pricing" not in profile.labels:
        return []
    scored: list[tuple[dict, float, list[str]]] = []
    for row in load_pricing_rows():
        score, reasons = _score_row(row, query, profile)
        if score >= min_score:
            scored.append((row, score, reasons))
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]
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
        docs.append(Document(page_content=content, metadata={
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
        }))
    logger.info(f"PricingRetriever: query='{query[:60]}' → {len(docs)} structured rows")
    return docs

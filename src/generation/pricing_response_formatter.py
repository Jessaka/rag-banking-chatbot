"""Deterministic pricing response formatter with conditional semantics."""

from __future__ import annotations

from typing import Any


def _money(value: Any, currency: str | None = "CZK") -> str:
    if value is None or value == "":
        return "neuvedeno"
    suffix = "Kč" if (currency or "CZK") == "CZK" else str(currency)
    return f"{value} {suffix}".strip()


def _period(period: str | None) -> str:
    return period or "měsíčně"


def condition_summary(condition_type: str | None, condition_text: str | None) -> str:
    if condition_text:
        return condition_text
    if condition_type == "active_usage":
        return "při aktivním využívání účtu"
    if condition_type == "turnover":
        return "při splnění podmínky obratu"
    if condition_type == "minimum_income":
        return "při splnění minimálního příjmu"
    if condition_type == "premium_tier":
        return "v prémiovém tarifu / při splnění prémiových podmínek"
    return "při splnění podmínek"


def format_conditional_fee(data: dict[str, Any]) -> str | None:
    if not data.get("conditional_pricing_detected"):
        return None
    product = data.get("product_name") or "Produkt"
    conditional_price = data.get("conditional_price")
    base_price = data.get("base_price")
    currency = data.get("currency") or "CZK"
    period = _period(data.get("period") or data.get("billing_period"))
    condition = condition_summary(data.get("condition_type"), data.get("condition_text"))

    if conditional_price == 0 and base_price is not None:
        return (
            f"{product} je zdarma {condition}.\n"
            f"Pokud podmínka splněna není, poplatek činí {_money(base_price, currency)} {period}."
        )
    if conditional_price is not None and base_price is not None:
        return (
            f"{product} má podmíněnou cenu {_money(conditional_price, currency)} {period} {condition}.\n"
            f"Bez splnění podmínky činí poplatek {_money(base_price, currency)} {period}."
        )
    if base_price is not None:
        return f"{product}: základní poplatek {_money(base_price, currency)} {period}; podmínka: {condition}."
    return f"{product}: cena je podmíněná; podmínka: {condition}."


def format_tiered_pricing(data: dict[str, Any]) -> list[str]:
    tiers = data.get("tiers") or []
    lines: list[str] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        label = tier.get("label") or tier.get("condition") or "Tarif"
        price = tier.get("price")
        currency = tier.get("currency") or data.get("currency") or "CZK"
        period = _period(tier.get("period") or data.get("period"))
        lines.append(f"* {label}: {_money(price, currency)} {period}")
    return lines

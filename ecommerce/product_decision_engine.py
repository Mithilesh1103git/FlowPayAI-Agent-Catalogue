"""Deterministic, category-agnostic product decision engine for FlowPayAI.

This module evaluates provider-backed product records. It does not call an LLM,
search providers, verify merchant pages independently, or authorize purchases.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

QUALIFIED = "qualified"
PARTIAL_MATCH = "partial_match"
REJECTED = "rejected"
INSUFFICIENT_DATA = "insufficient_data"

_SUPPORTED_STATUSES = {"supported_by_listing", "supported", "found_in_listing"}
_UNVERIFIED_STATUSES = {"unverified", "not_found", "unknown", "missing"}
_CONTRADICTED_STATUSES = {
    "contradicted_by_listing",
    "contradicted",
    "not_supported",
    "mismatch",
}


def _clean_currency(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def _valid_price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _normalize_requirements(requirements: Iterable[Any] | None) -> list[str]:
    """Accept strings or requirement dictionaries; deduplicate case-insensitively."""
    output: list[str] = []
    seen: set[str] = set()
    for item in requirements or []:
        if isinstance(item, str):
            label = item.strip()
        elif isinstance(item, dict):
            label = str(item.get("requirement") or item.get("name") or "").strip()
        else:
            continue
        key = label.casefold()
        if label and key not in seen:
            output.append(label)
            seen.add(key)
    return output


def _checks_by_requirement(product: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks = product.get("requirement_checks") or []
    result: dict[str, dict[str, Any]] = {}
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            label = str(check.get("requirement") or check.get("name") or "").strip()
            if label:
                result[label.casefold()] = check
    return result


def evaluate_product(
    product: dict[str, Any],
    requirements: Iterable[Any] | None = None,
    *,
    max_price: float | int | None = None,
    target_currency: str | None = None,
) -> dict[str, Any]:
    """Classify one product as qualified, partial_match, rejected, or insufficient_data.

    Rules:
    - A confirmed hard-constraint violation (over-budget, wrong currency, or a
      requirement explicitly contradicted by listing evidence) is REJECTED.
    - Missing price/currency needed for a requested budget check is INSUFFICIENT_DATA.
    - All requirements supported by listing evidence is QUALIFIED.
    - Some supported and some unverified requirements is PARTIAL_MATCH.
    - No usable requirement evidence is INSUFFICIENT_DATA.
    - With no specification requirements, valid price/currency data can qualify a
      product only when no budget check was requested; otherwise price eligibility
      is assessed first and the remaining classification is INSUFFICIENT_DATA.
    """
    if not isinstance(product, dict):
        return _result(
            INSUFFICIENT_DATA, "Product record is not a dictionary.", [], [], [], None
        )

    normalized_requirements = _normalize_requirements(requirements)
    checks = _checks_by_requirement(product)
    supported: list[str] = []
    unverified: list[str] = []
    contradicted: list[str] = []

    for requirement in normalized_requirements:
        check = checks.get(requirement.casefold())
        status = (
            str(check.get("status", "unverified")).strip().casefold()
            if check
            else "unverified"
        )
        if status in _SUPPORTED_STATUSES:
            supported.append(requirement)
        elif status in _CONTRADICTED_STATUSES:
            contradicted.append(requirement)
        else:
            # Unknown/missing status is never silently treated as supported.
            unverified.append(requirement)

    price = _valid_price(product.get("price"))
    currency = _clean_currency(product.get("currency"))
    budget = _valid_price(max_price) if max_price is not None else None
    requested_currency = _clean_currency(target_currency)

    if max_price is not None and budget is None:
        return _result(
            INSUFFICIENT_DATA,
            "The requested budget is not a valid finite non-negative number.",
            supported,
            unverified,
            contradicted,
            None,
        )

    # A budget check requires an actual price and a known currency.
    if budget is not None:
        if price is None or currency is None:
            return _result(
                INSUFFICIENT_DATA,
                "Cannot assess the budget because the listing lacks a usable price or currency.",
                supported,
                unverified,
                contradicted,
                None,
            )
        if requested_currency is None:
            requested_currency = currency
        if currency != requested_currency:
            return _result(
                REJECTED,
                f"Offer currency {currency} does not match requested currency {requested_currency}; currencies are not converted implicitly.",
                supported,
                unverified,
                contradicted,
                None,
            )
        if price > budget:
            return _result(
                REJECTED,
                f"Listed price {currency} {price:.2f} exceeds the budget of {requested_currency} {budget:.2f}.",
                supported,
                unverified,
                contradicted,
                None,
            )
    elif requested_currency and currency and currency != requested_currency:
        return _result(
            REJECTED,
            f"Offer currency {currency} does not match requested currency {requested_currency}.",
            supported,
            unverified,
            contradicted,
            None,
        )

    if contradicted:
        return _result(
            REJECTED,
            "Listing evidence contradicts one or more requested requirements.",
            supported,
            unverified,
            contradicted,
            _coverage(supported, normalized_requirements),
        )

    # Do not claim a match without a usable offer when a budget/currency constraint was requested.
    if (budget is not None or requested_currency is not None) and (
        price is None or currency is None
    ):
        return _result(
            INSUFFICIENT_DATA,
            "A usable price and currency are required to assess this offer.",
            supported,
            unverified,
            contradicted,
            _coverage(supported, normalized_requirements),
        )

    if not normalized_requirements:
        if budget is not None or requested_currency is not None:
            return _result(
                QUALIFIED,
                "The offer passes the available price and currency constraints; no specification requirements were supplied for assessment.",
                supported,
                unverified,
                contradicted,
                None,
            )
        return _result(
            INSUFFICIENT_DATA,
            "No product requirements or price constraints were supplied to assess this listing.",
            supported,
            unverified,
            contradicted,
            None,
        )

    if len(supported) == len(normalized_requirements):
        return _result(
            QUALIFIED,
            "Listing evidence supports every supplied requirement and no hard constraint failed.",
            supported,
            unverified,
            contradicted,
            1.0,
        )
    if supported:
        return _result(
            PARTIAL_MATCH,
            "Some requirements are supported by listing evidence; the remaining requirements are unverified.",
            supported,
            unverified,
            contradicted,
            _coverage(supported, normalized_requirements),
        )
    return _result(
        INSUFFICIENT_DATA,
        "The listing does not provide enough evidence to assess the requested specifications.",
        supported,
        unverified,
        contradicted,
        0.0,
    )


def rank_products(
    products: Iterable[dict[str, Any]],
    requirements: Iterable[Any] | None = None,
    *,
    max_price: float | int | None = None,
    target_currency: str | None = None,
) -> list[dict[str, Any]]:
    """Return copies of product records with decision fields, ordered by decision quality.

    Qualified first, then partial matches, insufficient data, and rejected products.
    Within each class, more supported requirements rank higher; then rating and price.
    Rejected items are retained at the end for transparency; callers can hide them.
    """
    priority = {QUALIFIED: 0, PARTIAL_MATCH: 1, INSUFFICIENT_DATA: 2, REJECTED: 3}
    ranked: list[dict[str, Any]] = []
    for original in products:
        product = (
            dict(original) if isinstance(original, dict) else {"raw_product": original}
        )
        decision = evaluate_product(
            product, requirements, max_price=max_price, target_currency=target_currency
        )
        product["decision_status"] = decision["status"]
        product["decision_reason"] = decision["reason"]
        product["supported_requirements"] = decision["supported_requirements"]
        product["unverified_requirements"] = decision["unverified_requirements"]
        product["contradicted_requirements"] = decision["contradicted_requirements"]
        product["requirement_coverage"] = decision["requirement_coverage"]
        ranked.append(product)

    def sort_key(product: dict[str, Any]) -> tuple[Any, ...]:
        status = product.get("decision_status", INSUFFICIENT_DATA)
        supported_count = len(product.get("supported_requirements") or [])
        rating = _valid_price(product.get("rating"))
        price = _valid_price(product.get("price"))
        return (
            priority.get(status, 2),
            -supported_count,
            -(rating if rating is not None else -1.0),
            price if price is not None else float("inf"),
            str(product.get("name") or "").casefold(),
        )

    ranked.sort(key=sort_key)
    return ranked


def _coverage(supported: list[str], requirements: list[str]) -> float | None:
    if not requirements:
        return None
    return round(len(supported) / len(requirements), 4)


def _result(
    status: str,
    reason: str,
    supported: list[str],
    unverified: list[str],
    contradicted: list[str],
    coverage: float | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "supported_requirements": supported,
        "unverified_requirements": unverified,
        "contradicted_requirements": contradicted,
        "requirement_coverage": coverage,
    }

"""Shopping Advisor Agent — explain evaluated products to the user."""

from __future__ import annotations

import json
import re
from typing import Any


def _normalize_name(name: Any) -> str:
    text = str(name or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _price_key(product: dict[str, Any]) -> str:
    price = product.get("price")
    currency = str(product.get("currency") or "").upper()
    try:
        return f"{currency}:{float(price):.2f}"
    except (TypeError, ValueError):
        return f"{currency}:na"


def _dedupe_for_display(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        fp = f"{_normalize_name(product.get('name'))}|{_price_key(product)}"
        if fp in seen:
            continue
        seen.add(fp)
        out.append(product)
    return out


def _pack(product: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "product_id": product.get("product_id"),
        "name": product.get("name"),
        "price": product.get("price"),
        "currency": product.get("currency"),
        "features": product.get("features", []),
        "decision_status": status,
        "supported_requirements": product.get("supported_requirements", []),
        "unverified_requirements": product.get("unverified_requirements", []),
        "decision_reason": product.get("decision_reason"),
        "shortlist_fallback": bool(product.get("shortlist_fallback")),
    }


def shopping_advisor_agent(state: dict) -> dict:
    """
    Present evaluated products and help the user choose.

    Never returns an empty dead-end if any products exist in state.
    """
    qualified_products = _dedupe_for_display(
        list(state.get("qualified_products") or [])
    )
    shortlisted = _dedupe_for_display(list(state.get("shortlisted_products") or []))
    all_products = _dedupe_for_display(list(state.get("products") or []))

    partial_products = [
        p for p in shortlisted if p.get("decision_status") == "partial_match"
    ]
    fallback_products = [
        p
        for p in shortlisted
        if p.get("decision_status") not in {"qualified", "partial_match"}
        or p.get("shortlist_fallback")
    ]
    # Avoid duplicating qualified/partial in fallback list
    qids = {p.get("product_id") for p in qualified_products}
    pids = {p.get("product_id") for p in partial_products}
    fallback_products = [
        p
        for p in fallback_products
        if p.get("product_id") not in qids and p.get("product_id") not in pids
    ]

    shopping_plan = state.get("shopping_plan", {}) or {}

    product_data = []
    for product in qualified_products:
        product_data.append(_pack(product, "qualified"))
    for product in partial_products:
        product_data.append(_pack(product, "partial_match"))
    for product in fallback_products:
        product_data.append(
            _pack(product, product.get("decision_status") or "insufficient_data")
        )

    # Last resort: any evaluated / research products
    if not product_data and all_products:
        for product in all_products[:8]:
            product_data.append(
                _pack(product, product.get("decision_status") or "insufficient_data")
            )

    if not product_data:
        return {
            "recommendation": (
                "I couldn't find usable product listings for this request. "
                "Try a broader query, a higher budget, or fewer required features."
            ),
            "status": "no_products_available",
        }

    confidence_note = ""
    if not qualified_products and (partial_products or fallback_products):
        confidence_note = (
            "\nNOTE TO ADVISOR: There are no fully qualified matches. "
            "Present the best available listings as partial or limited-evidence "
            "options. Clearly say which requirements are unverified. "
            "Do NOT say you found nothing.\n"
        )

    prompt = f"""
You are the Shopping Advisor for an AI-powered ecommerce assistant.
{confidence_note}
USER REQUEST:
{state.get("user_query", "")}

SHOPPING PLAN:
{json.dumps(shopping_plan, ensure_ascii=True)}

EVALUATED PRODUCTS:
{json.dumps(product_data, ensure_ascii=True)}

YOUR RESPONSIBILITIES:

1. Always recommend from the products provided above — never claim zero results if the list is non-empty.
2. Present fully qualified products first when any exist.
3. For partial_match or insufficient_data, label them clearly and list unverified requirements.
4. Mention price and listing features only from the data given.
5. Never invent specifications, prices, or ratings.
6. Never describe a partial/insufficient product as fully qualified.
7. Do not claim independent verification of merchant listings.
8. Help the user choose among the options provided.
9. Do not list two products with the same name and same price.
10. Keep the answer clear and user-friendly (tables are fine).

IMPORTANT:
You are an advisor, not a transaction agent.
Do not modify the cart or execute checkout.

Generate the final shopping recommendation.
"""

    try:
        from ecommerce.agents.model_config import get_llm

        llm = get_llm("advisor")
        response = llm.invoke(prompt)
        recommendation = (
            response.content if hasattr(response, "content") else str(response)
        )
        return {
            "recommendation": recommendation,
            "status": "recommendation_completed",
        }
    except Exception as error:
        # Deterministic fallback so the UI never goes blank on LLM errors
        lines = ["Here are the best available listings for your request:", ""]
        for i, item in enumerate(product_data, 1):
            lines.append(
                f"{i}. {item.get('name')} — {item.get('price')} {item.get('currency')} "
                f"[{item.get('decision_status')}]"
            )
        lines.append("")
        lines.append("Some requirements may be unverified in the listing text.")
        return {
            "recommendation": "\n".join(lines),
            "status": "advisor_fallback",
            "errors": [str(error)],
        }

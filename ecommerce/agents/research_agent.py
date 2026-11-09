"""Product Research Agent — optimize queries and search Channel3."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecommerce.agents.model_config import get_llm
from ecommerce.tools import EcommerceToolRegistry


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


def _dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by product_id, then by normalized name + price (+ retailer)."""
    by_id: dict[str, dict[str, Any]] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        pid = product.get("product_id")
        if not isinstance(pid, str) or not pid.strip():
            continue
        # Prefer listing with more feature text when same id appears again
        existing = by_id.get(pid)
        if existing is None:
            by_id[pid] = product
            continue
        old_feat = len(existing.get("features") or [])
        new_feat = len(product.get("features") or [])
        if new_feat > old_feat:
            by_id[pid] = product

    # Second pass: same title + price ≈ same SKU even if Channel3 ids / retailers differ
    seen_fp: set[str] = set()
    unique: list[dict[str, Any]] = []
    for product in by_id.values():
        name_key = _normalize_name(product.get("name"))
        fp = f"{name_key}|{_price_key(product)}"
        if not name_key:
            unique.append(product)
            continue
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        unique.append(product)
    return unique


def _expand_requirements(requirements: list[Any]) -> list[str]:
    """Expand common aliases so listing evidence matches more reliably."""
    expanded: list[str] = []
    seen: set[str] = set()

    alias_groups = [
        ("wireless", "bluetooth"),
        ("active noise cancellation", "anc", "noise cancelling", "noise canceling"),
        ("noise cancellation", "anc", "noise cancelling"),
    ]

    for raw in requirements or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = re.sub(r"\s+", " ", raw).strip()
        key = value.casefold()
        if key not in seen:
            expanded.append(value)
            seen.add(key)

        for group in alias_groups:
            group_cf = [g.casefold() for g in group]
            if any(g in key or key in g for g in group_cf):
                # Represent as one OR-requirement for evidence scoring
                or_label = " or ".join(group)
                if or_label.casefold() not in seen:
                    expanded.append(or_label)
                    seen.add(or_label.casefold())
                break

    return expanded


def research_agent(state: dict[str, Any]) -> dict[str, Any]:
    print("\n========== PRODUCT RESEARCH AGENT ==========")

    shopping_plan = state.get("shopping_plan", {})
    if not shopping_plan:
        return {
            "products": [],
            "errors": ["Shopping plan is missing."],
            "status": "research_failed",
        }

    if state.get("clarification_needed", False):
        return {
            "products": [],
            "status": "clarification_required",
        }

    category = shopping_plan.get("category")
    budget = shopping_plan.get("budget", {}) or {}
    max_price = budget.get("amount")
    currency = budget.get("currency")
    requirements = shopping_plan.get("must_have", []) or []
    original_queries = state.get("search_queries", []) or []

    if not original_queries:
        return {
            "products": [],
            "errors": ["No search queries available."],
            "status": "research_failed",
        }

    llm = get_llm("research")
    system_prompt = """
    You are the Product Research Agent of FlowPayAI.

    Your task is to optimize product search queries.

    You will receive:
    - Product category
    - Customer budget
    - Currency
    - Mandatory product requirements
    - Initial search queries

    Generate a maximum of three diverse search queries.

    Rules:
    1. Preserve the original product category.
    2. Preserve all important product specifications.
    3. Do not invent product requirements.
    4. Do not change the customer's budget.
    5. Avoid duplicate queries.
    6. Keep queries concise.

    Return ONLY valid JSON in this format:
    {
        "queries": [
            "search query 1",
            "search query 2",
            "search query 3"
        ]
    }
    """

    research_input = {
        "category": category,
        "budget": max_price,
        "currency": currency,
        "requirements": requirements,
        "original_queries": original_queries,
    }

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(research_input)),
    ]

    search_queries = list(original_queries)[:3]

    try:
        response = llm.invoke(messages)
        content = response.content
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str):
            raise ValueError("Unexpected LLM response format.")

        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise ValueError("Research model did not return valid JSON.")

        parsed = json.loads(match.group(0))
        generated_queries = parsed.get("queries", [])
        if not isinstance(generated_queries, list):
            raise ValueError("Queries must be a list.")

        validated_queries = [
            query.strip()
            for query in generated_queries
            if isinstance(query, str) and query.strip()
        ]
        if validated_queries:
            search_queries = list(dict.fromkeys(validated_queries))[:3]
    except Exception as exc:
        print("\nQuery optimization failed:", str(exc))
        print("Using Planner-generated search queries instead.")

    print("\nFinal Search Queries:")
    for query in search_queries:
        print("-", query)

    tool_registry = EcommerceToolRegistry()
    collected: list[dict[str, Any]] = []
    search_diagnostics: list[dict[str, Any]] = []
    search_features = _expand_requirements(
        [r for r in requirements if isinstance(r, str)]
    )

    for query in search_queries:
        print(f"\nSearching Channel3: {query}")
        response = tool_registry.search_products_multi_source(
            query=query,
            features=search_features or requirements,
            max_price=max_price,
            category=category,
            limit=10,
        )

        if not response.get("success"):
            search_diagnostics.append(
                {
                    "query": query,
                    "success": False,
                    "error": response.get("error"),
                }
            )
            print("Search failed:", response.get("error"))
            continue

        products = response.get("products", []) or []
        search_diagnostics.append(
            {
                "query": query,
                "success": True,
                "count": len(products),
            }
        )
        for product in products:
            if isinstance(product, dict):
                collected.append(product)
        print("Products retrieved:", len(products))

    final_products = _dedupe_products(collected)

    print("\n========== RESEARCH SUMMARY ==========")
    print("Queries executed:", len(search_queries))
    print("Raw collected:", len(collected))
    print("Unique products after dedupe:", len(final_products))

    errors: list[str] = []
    if not final_products:
        errors.append("No products were retrieved from Channel3.")

    return {
        "products": final_products,
        "errors": errors,
        "status": "research_completed" if final_products else "research_failed",
        "search_diagnostics": search_diagnostics,
    }

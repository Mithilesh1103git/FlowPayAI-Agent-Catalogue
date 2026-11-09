"""Pass prior-turn products into the pipeline (no Channel3 call)."""

from __future__ import annotations

from typing import Any


def use_existing_products_agent(state: dict[str, Any]) -> dict[str, Any]:
    """
    Refine path: reuse products from the previous turn.

    Planner has already updated must_have / budget from the follow-up
    (e.g. 1TB SSD). Evaluation will re-rank these products under the new plan.
    """
    print("\n========== USE EXISTING PRODUCTS (refine, no new search) ==========")

    prior = state.get("prior_products") or []
    products = [p for p in prior if isinstance(p, dict)]

    print(f"Prior products loaded: {len(products)}")

    if not products:
        return {
            "products": [],
            "errors": [
                "No products from the previous turn are available to refine. "
                "Please run a new product search."
            ],
            "status": "refine_failed",
        }

    return {
        "products": products,
        "errors": [],
        "status": "using_existing_products",
    }

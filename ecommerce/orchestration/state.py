from typing import Any, TypedDict


class ShoppingState(TypedDict, total=False):
    # User input
    user_query: str
    messages: list

    # Prior turn products (for refine follow-ups)
    prior_products: list
    use_existing_products: bool

    # Planner
    shopping_plan: dict
    search_queries: list
    clarification_needed: bool

    # Research / refine
    products: list

    # Evaluation
    evaluations: list
    qualified_products: list
    shortlisted_products: list

    # Shopping Advisor
    recommendation: Any

    # Cart and checkout (filled by UI, not graph)
    cart: dict
    checkout_details: dict

    # Policy
    policy_intent: dict

    # Workflow control
    retry_count: int
    max_retries: int
    next_action: str
    status: str
    errors: list


def initialize_state(
    user_query: str,
    *,
    prior_products: list | None = None,
    use_existing_products: bool = False,
) -> ShoppingState:
    prior = [p for p in (prior_products or []) if isinstance(p, dict)]
    return {
        "user_query": user_query,
        "messages": [],
        "prior_products": prior,
        "use_existing_products": bool(use_existing_products and prior),
        "shopping_plan": {},
        "search_queries": [],
        "clarification_needed": False,
        "products": [],
        "evaluations": [],
        "qualified_products": [],
        "shortlisted_products": [],
        "recommendation": None,
        "cart": {},
        "checkout_details": {},
        "policy_intent": {},
        "retry_count": 0,
        "max_retries": 2,
        "next_action": "",
        "status": "initialized",
        "errors": [],
    }

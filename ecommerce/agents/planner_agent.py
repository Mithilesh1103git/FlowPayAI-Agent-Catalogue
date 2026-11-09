from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ecommerce.agents.model_config import get_llm

# ==========================================
# STRUCTURED OUTPUT SCHEMA
# ==========================================


class Budget(BaseModel):

    amount: Optional[float] = None

    currency: Optional[str] = None


class ShoppingPlan(BaseModel):

    category: str = Field(description="The product category requested by the customer")

    budget: Budget = Field(description="The customer's budget and currency")

    must_have: list[str] = Field(description="Mandatory product requirements")

    preferences: list[str] = Field(description="Optional product preferences")

    search_queries: list[str] = Field(
        description="Product search queries for the research agent"
    )

    clarification_needed: bool = Field(
        description="Whether essential shopping information is missing"
    )

    clarification_reason: Optional[str] = Field(
        default=None, description="Explanation of why clarification is required"
    )


# ==========================================
# SHOPPING PLANNER AGENT
# ==========================================


def planner_agent(state: dict) -> dict:

    print("\n========== SHOPPING PLANNER ==========")

    user_query = state["user_query"]
    prior_products = state.get("prior_products") or []
    use_existing = bool(state.get("use_existing_products"))

    prior_lines: list[str] = []
    for product in prior_products[:20]:
        if not isinstance(product, dict):
            continue
        name = product.get("name") or "Unknown product"
        price = product.get("price")
        currency = product.get("currency") or ""
        product_id = product.get("product_id") or ""
        features = product.get("features") or []
        if isinstance(features, list):
            feature_hint = "; ".join(str(f) for f in features[:6] if str(f).strip())
        else:
            feature_hint = str(features)
        prior_lines.append(
            f"- {name} | {price} {currency} | id={product_id} | features: {feature_hint}"
        )
    prior_block = "\n".join(prior_lines) if prior_lines else "(none)"

    llm = get_llm("planner")
    structured_llm = llm.with_structured_output(ShoppingPlan, method="function_calling")

    system_prompt = """
You are the Shopping Planner Agent of FlowPayAI.

Your responsibility is to understand customer shopping
requirements and convert them into a structured shopping plan.

Follow these rules:

1. Identify the product category.

2. Extract the customer's budget and currency.

3. Identify mandatory requirements (must_have).

4. Identify optional preferences.

5. Generate relevant product search queries (for a NEW search only).

6. Never invent requirements that the customer did not specify.

7. Do not assume a budget if the customer has not provided one.

8. If the customer does not specify currency, leave it null.
   Do not infer currency from location.

9. Clarification rules:
   - Set clarification_needed to true ONLY when you cannot tell what
     product category the user wants at all (empty or pure gibberish).
   - A budget, brand, or feature can be missing — still plan a search;
     do not block on missing optional details.
   - If "Products already shown to the customer" is non-empty and
     the user is filtering, ranking, removing, or refining that list,
     set clarification_needed to FALSE even if model names are not
     repeated in the message. Use the provided product list as context.
   - Do NOT ask the user to re-list models that are already in
     "Products already shown".

10. When the user adds constraints on an existing list
    (e.g. "remove models with less than 1TB SSD", "keep RTX 4060"),
    put those constraints into must_have and keep the category.

11. Keep search_queries concise. If this is clearly a refine-only
    follow-up on existing products, search_queries may be empty or
    briefly echo the category.

Return only the structured shopping plan.
"""

    human_content = f"""Customer message:
{user_query}

Products already shown to the customer (if any):
{prior_block}

Refine mode (skip new catalog search if true): {use_existing}

Build the shopping plan. If products are already shown and the customer
is refining that set, do not request clarification for missing model names.
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    result = structured_llm.invoke(messages)
    shopping_plan = result.model_dump()

    # Safety: never block refine-only turns solely on clarification when we have priors
    if use_existing and prior_products:
        shopping_plan["clarification_needed"] = False
        if not shopping_plan.get("clarification_reason"):
            shopping_plan["clarification_reason"] = None

    print("\nShopping Plan:")
    print(shopping_plan)

    return {
        "shopping_plan": shopping_plan,
        "search_queries": shopping_plan.get("search_queries") or [],
        "clarification_needed": shopping_plan.get("clarification_needed", False),
        "status": "planning_completed",
    }

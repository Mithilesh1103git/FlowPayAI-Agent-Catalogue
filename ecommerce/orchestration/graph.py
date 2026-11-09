from langgraph.graph import END, START, StateGraph

from ecommerce.agents.evaluation_agent import evaluation_agent
from ecommerce.agents.planner_agent import planner_agent
from ecommerce.agents.research_agent import research_agent
from ecommerce.agents.shopping_advisor_agent import shopping_advisor_agent
from ecommerce.agents.use_existing_products_agent import use_existing_products_agent
from ecommerce.orchestration.routing import route_after_evaluation, route_after_planner
from ecommerce.orchestration.state import ShoppingState, initialize_state


def build_shopping_graph():
    workflow = StateGraph(ShoppingState)

    workflow.add_node("planner", planner_agent)
    workflow.add_node("research", research_agent)
    workflow.add_node("use_existing", use_existing_products_agent)
    workflow.add_node("evaluation", evaluation_agent)
    workflow.add_node("advisor", shopping_advisor_agent)

    workflow.add_edge(START, "planner")

    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "research": "research",
            "use_existing": "use_existing",
            "end": END,
        },
    )

    workflow.add_edge("research", "evaluation")
    workflow.add_edge("use_existing", "evaluation")

    workflow.add_conditional_edges(
        "evaluation",
        route_after_evaluation,
        {
            "advisor": "advisor",
        },
    )

    workflow.add_edge("advisor", END)

    return workflow.compile()


shopping_graph = build_shopping_graph()


def _is_refine_request(message: str) -> bool:
    """Heuristic: user wants to filter/rank the previous result set."""
    import re

    text = message.casefold()
    patterns = (
        r"from the (laptops|products|items|ones|list|results) you",
        r"you just recommended",
        r"from (these|those|the current|the previous)",
        r"do not (perform|run|do) a new (product )?search",
        r"without (a )?(new )?search",
        r"don't (perform|run) a new search",
        r"remove every (model|product|item)",
        r"filter (the|these|those)",
        r"only keep",
        r"rank the remaining",
        r"existing listings",
    )
    return any(re.search(p, text) for p in patterns)


def run_shopping_workflow(
    user_query: str,
    *,
    prior_products: list | None = None,
    force_refine: bool | None = None,
):
    """
    Run the multi-agent shopping graph.

    prior_products: products from the previous turn (session).
    force_refine: if True, skip Channel3 when prior_products exist.
                  if None, auto-detect refine language in user_query.
    """
    prior = [p for p in (prior_products or []) if isinstance(p, dict)]
    if force_refine is None:
        use_existing = bool(prior) and _is_refine_request(user_query)
    else:
        use_existing = bool(force_refine and prior)

    initial_state = initialize_state(
        user_query,
        prior_products=prior,
        use_existing_products=use_existing,
    )
    result = shopping_graph.invoke(initial_state)
    return result

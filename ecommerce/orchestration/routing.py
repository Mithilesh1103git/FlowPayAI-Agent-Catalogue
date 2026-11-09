"""Routing helpers for the shopping LangGraph."""


def route_after_planner(state: dict) -> str:
    """
    After planning:
    - clarification → end
    - refine follow-up with prior products → use_existing (skip Channel3)
    - otherwise → research (new Channel3 search)
    """
    if state.get("clarification_needed", False):
        return "end"

    if state.get("use_existing_products") and state.get("prior_products"):
        return "use_existing"

    return "research"


def route_after_evaluation(state: dict) -> str:
    """Always send evaluation output to the advisor (handles empty lists)."""
    return "advisor"

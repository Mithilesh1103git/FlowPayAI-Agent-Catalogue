"""TaskWorker — dispatches ecommerce shopping to the multi-agent LangGraph workflow."""

from __future__ import annotations

from typing import Any


class TaskWorker:
    """Central dispatcher for FlowPayAI multi-agent shopping."""

    SUPPORTED_AGENTS = {"ecommerce"}

    def __init__(self) -> None:
        self._graph_ready = False

    def validate_task_request(self, request: dict) -> dict:
        errors: list[str] = []
        if not isinstance(request, dict):
            return {"valid": False, "errors": ["Task request must be a dictionary."]}

        agent = request.get("agent")
        payload = request.get("payload")

        if not isinstance(agent, str) or not agent.strip():
            errors.append("A non-empty agent name is required.")
        elif agent not in self.SUPPORTED_AGENTS:
            errors.append(f"Unsupported agent: {agent}.")

        if not isinstance(payload, dict):
            errors.append("payload must be a dictionary.")

        return {"valid": not errors, "errors": errors}

    def process_task(self, request: dict) -> dict[str, Any]:
        return self.dispatch_task(request)

    def dispatch_task(self, request: dict) -> dict[str, Any]:
        validation = self.validate_task_request(request)
        if not validation["valid"]:
            return {
                "success": False,
                "agent": (request.get("agent") if isinstance(request, dict) else None),
                "status": "validation_failed",
                "errors": validation["errors"],
                "message": "; ".join(validation["errors"]),
                "products": [],
                "tool_calls": [],
            }

        payload = request["payload"]
        message = payload.get("message", payload.get("query", ""))
        if not isinstance(message, str) or not message.strip():
            return {
                "success": False,
                "agent": "ecommerce",
                "status": "validation_failed",
                "message": "Provide a non-empty 'message' in the payload.",
                "products": [],
                "tool_calls": [],
            }

        current_products = payload.get("current_products") or []
        if not isinstance(current_products, list):
            current_products = []

        try:
            from ecommerce.orchestration.graph import run_shopping_workflow

            result = run_shopping_workflow(
                message.strip(),
                prior_products=current_products,
            )

            clarification = bool(result.get("clarification_needed"))
            plan = result.get("shopping_plan") or {}
            products = (
                result.get("shortlisted_products")
                or result.get("qualified_products")
                or result.get("products")
                or []
            )
            if not isinstance(products, list):
                products = []

            recommendation = result.get("recommendation")
            status = result.get("status") or "completed"
            errors = result.get("errors") or []
            if not isinstance(errors, list):
                errors = [str(errors)]

            if clarification:
                reason = (
                    plan.get("clarification_reason") if isinstance(plan, dict) else None
                ) or "Please provide more details about your shopping request."
                return {
                    "success": True,
                    "agent": "ecommerce",
                    "status": "clarification_required",
                    "message": reason,
                    "products": current_products,
                    "shopping_plan": plan,
                    "clarification_needed": True,
                    "tool_calls": [],
                    "result": result,
                }

            if not recommendation:
                if errors:
                    recommendation = "Search finished with issues: " + "; ".join(
                        str(e) for e in errors
                    )
                elif not products:
                    recommendation = (
                        "No matching products were found for this request. "
                        "Try adjusting budget or requirements, or run a new search."
                    )
                else:
                    recommendation = (
                        f"Found {len(products)} product(s). "
                        "Review the list and add items to your cart."
                    )

            return {
                "success": True,
                "agent": "ecommerce",
                "status": status,
                "message": (
                    recommendation
                    if isinstance(recommendation, str)
                    else str(recommendation)
                ),
                "products": products,
                "shopping_plan": plan,
                "qualified_products": result.get("qualified_products") or [],
                "shortlisted_products": result.get("shortlisted_products") or [],
                "clarification_needed": False,
                "tool_calls": [],
                "errors": errors,
                "result": result,
            }

        except Exception as exc:
            return {
                "success": False,
                "agent": "ecommerce",
                "status": "agent_error",
                "message": f"Multi-agent shopping workflow failed: {exc}",
                "products": [],
                "tool_calls": [],
            }

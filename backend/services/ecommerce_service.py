from backend.database.sqlite import audit, record_workflow
from taskworker import TaskWorker


class EcommerceService:
    def __init__(self):
        self.worker = TaskWorker()

    def search(self, query, prior_products=None, session_id=None):
        result = self.worker.process_task(
            {
                "pipeline": "ecommerce",
                "payload": {"message": query, "current_products": prior_products or []},
            }
        )
        if result.get("success"):
            execution_id = record_workflow(query, result, session_id)
            result["execution_id"] = execution_id
        else:
            audit(
                "workflow.failed",
                "workflow",
                actor="user",
                severity="ERROR",
                details={"query": query, "message": result.get("message")},
            )
        return result

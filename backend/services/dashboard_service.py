from backend.database.sqlite import rows


def metrics():
    return {
        "workflows": rows("SELECT COUNT(*) n FROM workflow_executions")[0]["n"],
        "products": rows("SELECT COUNT(*) n FROM products")[0]["n"],
        "payments": rows("SELECT COUNT(*) n FROM payment_orders")[0]["n"],
        "audit_events": rows("SELECT COUNT(*) n FROM audit_events")[0]["n"],
        "payment_status": rows(
            "SELECT status, COUNT(*) count FROM payment_orders GROUP BY status"
        ),
        "workflow_status": rows(
            "SELECT status, COUNT(*) count FROM workflow_executions GROUP BY status"
        ),
        "recent": rows(
            "SELECT execution_id,query,status,product_count,started_at FROM workflow_executions ORDER BY started_at DESC LIMIT 15"
        ),
    }

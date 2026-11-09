from backend.database.sqlite import audit, rows


def log_event(event_type, **kwargs):
    return audit(event_type, **kwargs)


def list_events(limit=500):
    return rows(
        "SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT ?", (int(limit),)
    )

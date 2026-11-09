import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers import webhooks


def build_request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/"}, receive)


@pytest.mark.asyncio
async def test_transaction_refused_is_acknowledged(monkeypatch, tmp_path):
    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "capture-webhook.sqlite3")
    db.init_db()
    db.save_payment_order("ORDER-123", "checkout-123", "10.00", "USD", "CREATED", {})
    event = {
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "ORDER-123", "status": "APPROVED"},
    }
    refusal = {
        "name": "UNPROCESSABLE_ENTITY",
        "details": [{"issue": "TRANSACTION_REFUSED"}],
        "debug_id": "debug-123",
    }
    monkeypatch.setattr(
        webhooks.paypal_service,
        "verify_webhook_signature",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        webhooks.paypal_service,
        "capture_order",
        AsyncMock(side_effect=HTTPException(status_code=422, detail=refusal)),
    )

    response = await webhooks.paypal_webhook(build_request(event))

    assert response == {
        "status": "received",
        "capture_status": "DENIED",
        "capture_reason": "TRANSACTION_REFUSED",
        "fulfillment_status": "failed",
        "fulfillment_allowed": False,
        "order_id": "ORDER-123",
        "paypal_debug_id": "debug-123",
    }


@pytest.mark.asyncio
async def test_verified_webhook_is_deduplicated_after_success(tmp_path, monkeypatch):
    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "webhook-dedup.sqlite3")
    db.init_db()
    event = {
        "id": "WH-EVENT-DEDUP-1",
        "event_type": "SOME.UNHANDLED.EVENT",
        "resource": {"id": "RESOURCE-1"},
    }
    monkeypatch.setattr(
        webhooks.paypal_service,
        "verify_webhook_signature",
        AsyncMock(return_value=True),
    )

    first = await webhooks.paypal_webhook(build_request(event))
    second = await webhooks.paypal_webhook(build_request(event))

    assert first == {"status": "received", "capture_status": "ignored"}
    assert second == {
        "status": "duplicate_ignored",
        "event_id": "WH-EVENT-DEDUP-1",
    }
    saved = db.rows(
        "SELECT processing_status FROM webhook_events WHERE event_id=?",
        ("WH-EVENT-DEDUP-1",),
    )
    assert saved[0]["processing_status"] == "processed"

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.app_order import AppOrderInput
from app.services.order_adapter import build_paypal_order_payload

SAMPLE_PAYLOAD = {
    "schema_version": "1.0",
    "checkout_intent_id": "chk_6b4483f5de1e425e",
    "cart_id": "cart-1de18fbd6293",
    "status": "ready_for_payment_team",
    "currency": "USD",
    "amount": {
        "value": "52.99",
        "currency": "USD",
        "minor_units": 5299,
    },
    "items": [
        {
            "product_id": "channel3_dsJDkOf",
            "name": "Noise Cancelling Wireless Over Ear Headphones",
            "retailer": "walmart.com",
            "product_url": "https://buy.trychannel3.com/sample",
            "quantity": 1,
            "unit_price": "52.99",
            "line_total": "52.99",
            "currency": "USD",
        }
    ],
    "item_count": 1,
    "total_quantity": 1,
    "source": {"provider": "channel3", "checkout_mode": "on_site_cart"},
    "approval": {
        "decision_id": "rev-123",
        "decision": "user_approved",
        "purchase_request_id": None,
    },
    "policy": {"execution_authorized": False, "execution_performed": False},
    "notes": ["Test notes"],
}


def test_valid_schema_and_adapter():
    validated = AppOrderInput.model_validate(SAMPLE_PAYLOAD)
    assert validated.amount.value == Decimal("52.99")

    paypal_payload = build_paypal_order_payload(
        validated, "https://example.com/return", "https://example.com/cancel"
    )
    assert paypal_payload["intent"] == "CAPTURE"
    unit = paypal_payload["purchase_units"][0]
    assert unit["invoice_id"] == "chk_6b4483f5de1e425e"
    assert unit["amount"]["value"] == "52.99"
    assert unit["items"][0]["sku"] == "channel3_dsJDkOf"


def test_mismatched_totals():
    bad_payload = dict(SAMPLE_PAYLOAD)
    bad_payload["amount"] = {"value": "100.00", "currency": "USD"}
    with pytest.raises(ValidationError):
        AppOrderInput.model_validate(bad_payload)

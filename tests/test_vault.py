from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.schemas.app_order import AppOrderInput
from app.services.order_adapter import build_paypal_order_payload
from backend.services.payment_service import PaymentService

SAMPLE_ORDER = {
    "schema_version": "1.0",
    "checkout_intent_id": "checkout-vault-test",
    "cart_id": "cart-vault-test",
    "status": "ready_for_payment_team",
    "currency": "USD",
    "amount": {"value": "10.00", "currency": "USD", "minor_units": 1000},
    "items": [
        {
            "product_id": "sku-1",
            "name": "Test item",
            "retailer": "example.com",
            "quantity": 1,
            "unit_price": "10.00",
            "line_total": "10.00",
            "currency": "USD",
        }
    ],
    "item_count": 1,
    "total_quantity": 1,
    "source": {"provider": "test"},
    "approval": {"decision": "user_approved"},
    "policy": {"execution_authorized": False, "execution_performed": False},
}


def test_vault_opt_in_adds_paypal_vault_instruction():
    order = AppOrderInput.model_validate(deepcopy(SAMPLE_ORDER))
    payload = build_paypal_order_payload(
        order,
        "https://example.com/return",
        "https://example.com/cancel",
        save_payment_method=True,
        buyer_id="buyer-123",
    )
    paypal = payload["payment_source"]["paypal"]
    assert paypal["attributes"]["vault"] == {
        "store_in_vault": "ON_SUCCESS",
        "usage_type": "MERCHANT",
    }
    assert paypal["attributes"]["customer"]["merchant_customer_id"] == "buyer-123"
    assert paypal["experience_context"]["return_url"] == "https://example.com/return"


def test_normal_paypal_checkout_does_not_request_vault():
    order = AppOrderInput.model_validate(deepcopy(SAMPLE_ORDER))
    payload = build_paypal_order_payload(
        order,
        "https://example.com/return",
        "https://example.com/cancel",
    )
    paypal = payload["payment_source"]["paypal"]
    assert "attributes" not in paypal
    assert "vault_id" not in paypal


def test_saved_token_checkout_is_gated_until_rda_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PAYPAL_VAULT_ENABLED", True)
    monkeypatch.setattr(settings, "PAYPAL_VAULT_CHARGES_ENABLED", False)

    with pytest.raises(RuntimeError, match="FraudNet/Magnes"):
        import asyncio

        asyncio.run(
            PaymentService.create_order_from_checkout(
                deepcopy(SAMPLE_ORDER),
                buyer_id="buyer-123",
                saved_method_id="saved-method-1",
            )
        )


def test_vault_created_webhook_persists_encrypted_token(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vault-test.sqlite3")
    monkeypatch.setattr(
        settings,
        "PAYPAL_VAULT_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    db.init_db()
    db.save_vault_order_intent("ORDER-OPTED-IN", "buyer-vault-test")
    result = PaymentService.process_vault_webhook(
        "VAULT.PAYMENT-TOKEN.CREATED",
        {
            "id": "PAYPAL-TOKEN-456",
            "customer": {
                "id": "PAYPAL-CUSTOMER-1",
                "merchant_customer_id": "buyer-vault-test",
            },
        },
    )
    methods = PaymentService.get_saved_methods("buyer-vault-test")
    assert result["status"] == "saved"
    assert len(methods) == 1

    stored = db.rows("SELECT vault_id_ciphertext, vault_id_hash FROM payment_methods")[
        0
    ]
    assert stored["vault_id_ciphertext"] != "PAYPAL-TOKEN-456"
    assert stored["vault_id_hash"]


def test_vault_created_webhook_is_not_saved_without_buyer_mapping(
    tmp_path, monkeypatch
):
    from cryptography.fernet import Fernet

    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vault-unmatched.sqlite3")
    monkeypatch.setattr(
        settings,
        "PAYPAL_VAULT_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    db.init_db()
    result = PaymentService.process_vault_webhook(
        "VAULT.PAYMENT-TOKEN.CREATED",
        {"id": "TOKEN-UNMATCHED", "customer": {"id": "UNKNOWN"}},
    )
    assert result["status"] == "unmatched"


def test_us_paypal_build_rejects_non_usd_checkout():
    import asyncio

    non_usd = deepcopy(SAMPLE_ORDER)
    non_usd["currency"] = "INR"
    non_usd["amount"]["currency"] = "INR"
    non_usd["items"][0]["currency"] = "INR"
    with pytest.raises(ValueError, match="USD checkout only"):
        asyncio.run(
            PaymentService.create_order_from_checkout(
                non_usd,
                buyer_id="buyer-inr",
            )
        )


@pytest.mark.asyncio
async def test_payment_service_creates_normal_order_without_vault(
    tmp_path, monkeypatch
):
    from app.services.paypal_client import paypal_service
    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "normal-payment.sqlite3")
    db.init_db()
    monkeypatch.setattr(settings, "PAYPAL_VAULT_ENABLED", False)
    monkeypatch.setattr(settings, "PAYPAL_VAULT_CHARGES_ENABLED", False)
    create_mock = AsyncMock(
        return_value={
            "id": "ORDER-NORMAL-1",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://paypal.test/approve"}],
        }
    )
    monkeypatch.setattr(paypal_service, "create_order", create_mock)

    result = await PaymentService.create_order_from_checkout(
        deepcopy(SAMPLE_ORDER),
        buyer_id="buyer-normal",
    )

    sent_payload = create_mock.await_args.args[0]
    assert "attributes" not in sent_payload["payment_source"]["paypal"]
    assert result["approval_url"] == "https://paypal.test/approve"
    assert result["vault_opt_in"] is False
    assert db.rows(
        "SELECT paypal_order_id FROM payment_orders WHERE paypal_order_id=?",
        ("ORDER-NORMAL-1",),
    )


@pytest.mark.asyncio
async def test_payment_service_records_explicit_vault_opt_in(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    from app.services.paypal_client import paypal_service
    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vault-opt-in.sqlite3")
    db.init_db()
    monkeypatch.setattr(settings, "PAYPAL_VAULT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "PAYPAL_VAULT_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    create_mock = AsyncMock(
        return_value={
            "id": "ORDER-VAULT-OPTIN",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://paypal.test/approve"}],
        }
    )
    monkeypatch.setattr(paypal_service, "create_order", create_mock)

    result = await PaymentService.create_order_from_checkout(
        deepcopy(SAMPLE_ORDER),
        buyer_id="buyer-opt-in",
        save_method=True,
    )

    sent_payload = create_mock.await_args.args[0]
    assert (
        sent_payload["payment_source"]["paypal"]["attributes"]["vault"][
            "store_in_vault"
        ]
        == "ON_SUCCESS"
    )
    assert result["vault_opt_in"] is True
    intent = db.rows(
        "SELECT buyer_id, save_requested FROM vault_order_intents WHERE paypal_order_id=?",
        ("ORDER-VAULT-OPTIN",),
    )
    assert intent == [{"buyer_id": "buyer-opt-in", "save_requested": 1}]


@pytest.mark.asyncio
async def test_capture_reuses_persisted_rda_correlation_id(tmp_path, monkeypatch):
    from app.services.paypal_client import paypal_service
    from backend.database import sqlite as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rda-metadata.sqlite3")
    db.init_db()
    db.save_payment_order(
        "ORDER-RDA-1",
        "checkout-rda-1",
        "10.00",
        "USD",
        "CREATED",
        {"_flowpay_client_metadata_id": "risk-correlation-123"},
    )
    capture_mock = AsyncMock(
        return_value={
            "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [{"status": "COMPLETED"}]}}],
        }
    )
    monkeypatch.setattr(paypal_service, "capture_order", capture_mock)

    await PaymentService.capture_order("ORDER-RDA-1")

    assert (
        capture_mock.await_args.kwargs["client_metadata_id"] == "risk-correlation-123"
    )

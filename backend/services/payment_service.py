"""In-process payment application service shared by Streamlit and FastAPI.

The UI calls these static methods directly. FastAPI routes are retained only
for external PayPal webhooks and browser return/cancel callbacks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.app_order import AppOrderInput
from app.services.order_adapter import build_paypal_order_payload
from app.services.paypal_client import paypal_service
from backend.database.sqlite import (
    audit,
    delete_payment_method_local,
    get_buyer_for_paypal_customer,
    get_payment_method,
    get_vault_order_intent,
    has_vault_opt_in_for_buyer,
    list_payment_methods,
    rows,
    save_payment_method,
    save_payment_order,
    save_vault_customer,
    save_vault_order_intent,
    set_payment_method_status_by_hash,
    update_payment_status,
)


class PaymentService:
    """Application-level payment use cases; methods are callable in-process."""

    @staticmethod
    def _fernet() -> Fernet:
        key = settings.PAYPAL_VAULT_ENCRYPTION_KEY
        if not key:
            raise RuntimeError(
                "PAYPAL_VAULT_ENCRYPTION_KEY is required to save PayPal tokens. "
                "Generate one with Fernet.generate_key()."
            )
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "PAYPAL_VAULT_ENCRYPTION_KEY is not a valid Fernet key."
            ) from exc

    @staticmethod
    def _approval_url(response: dict) -> str | None:
        return next(
            (
                link.get("href")
                for link in response.get("links", [])
                if link.get("rel") in {"payer-action", "approve"}
            ),
            None,
        )

    @staticmethod
    async def create_order_from_checkout(
        checkout_data: dict,
        *,
        buyer_id: str,
        save_method: bool = False,
        saved_method_id: str | None = None,
        client_metadata_id: str | None = None,
    ) -> dict:
        if save_method and saved_method_id:
            raise ValueError(
                "Choose either a new PayPal vault opt-in or an existing saved method."
            )
        if save_method and not settings.PAYPAL_VAULT_ENABLED:
            raise RuntimeError(
                "PayPal Vault enrollment is disabled. Enable it only after the PayPal merchant "
                "app has Vault capability and the merchant account is approved."
            )
        if save_method:
            if not buyer_id or len(buyer_id) > 64:
                raise ValueError(
                    "Vault enrollment requires a buyer_id between 1 and 64 characters."
                )
            # Fail before creating/charging an order if the token cannot be encrypted.
            PaymentService._fernet()
        if saved_method_id and not (
            settings.PAYPAL_VAULT_ENABLED
            and settings.PAYPAL_VAULT_CHARGES_ENABLED
            and settings.PAYPAL_RDA_ENABLED
        ):
            raise RuntimeError(
                "Saved-token checkout is disabled until PayPal FraudNet/Magnes risk-data "
                "collection, client-generated correlation ID, and merchant eligibility are configured."
            )

        if saved_method_id and not client_metadata_id:
            raise RuntimeError(
                "Saved-token checkout requires a PayPal RDA correlation ID from the client."
            )

        validated = AppOrderInput.model_validate(checkout_data)
        if (
            validated.currency.upper() != "USD"
            or validated.amount.currency.upper() != "USD"
        ):
            raise ValueError(
                "This US PayPal Sandbox build currently accepts USD checkout only."
            )
        if any(item.currency.upper() != "USD" for item in validated.items):
            raise ValueError("Every checkout item must use USD in the US PayPal build.")
        vault_id = None
        if saved_method_id:
            record = get_payment_method(saved_method_id, buyer_id)
            if not record:
                raise ValueError("The selected saved PayPal method is unavailable.")
            try:
                vault_id = (
                    PaymentService._fernet()
                    .decrypt(record["vault_id_ciphertext"].encode())
                    .decode()
                )
            except InvalidToken as exc:
                raise RuntimeError(
                    "The saved PayPal token could not be decrypted."
                ) from exc

        payload = build_paypal_order_payload(
            validated,
            return_url=settings.APP_RETURN_URL,
            cancel_url=settings.APP_CANCEL_URL,
            save_payment_method=save_method,
            buyer_id=buyer_id,
            vault_id=vault_id,
        )
        request_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"flowpayai:paypal:create:{validated.checkout_intent_id}",
            )
        )
        response = await paypal_service.create_order(
            payload,
            client_metadata_id=client_metadata_id,
            request_id=request_id,
        )
        order_id = response.get("id")
        if not order_id:
            raise RuntimeError("PayPal did not return an order ID.")

        stored_response = dict(response)
        if client_metadata_id:
            stored_response["_flowpay_client_metadata_id"] = client_metadata_id
        save_payment_order(
            order_id,
            validated.checkout_intent_id,
            validated.amount.value,
            validated.currency,
            response.get("status", "CREATED"),
            stored_response,
        )
        if save_method:
            save_vault_order_intent(order_id, buyer_id)
        audit(
            "paypal.order_created",
            "payment_order",
            order_id,
            details={
                "checkout_id": validated.checkout_intent_id,
                "amount": str(validated.amount.value),
                "currency": validated.currency,
                "vault_opt_in": bool(save_method),
                "saved_method_used": bool(saved_method_id),
            },
        )
        return {
            "status": "created",
            "order_id": order_id,
            "paypal_status": response.get("status"),
            "approval_url": PaymentService._approval_url(response),
            "vault_opt_in": bool(save_method),
            "saved_method_used": bool(saved_method_id),
            "raw_response": response,
        }

    @staticmethod
    def _persist_capture_result(order_id: str, response: dict) -> None:
        status = response.get("purchase_units", [{}])[0].get("payments", {}).get(
            "captures", [{}]
        )[0].get("status") or response.get("status", "UNKNOWN")
        update_payment_status(order_id, status, response)

        intent = get_vault_order_intent(order_id)
        paypal_source = response.get("payment_source", {}).get("paypal", {})
        vault = paypal_source.get("attributes", {}).get("vault", {})
        vault_id = vault.get("id")
        vault_status = vault.get("status")
        customer = vault.get("customer") or {}
        paypal_customer_id = customer.get("id")
        merchant_customer_id = customer.get("merchant_customer_id")

        # Map PayPal's customer record for a later token-created webhook.
        if intent and paypal_customer_id:
            save_vault_customer(paypal_customer_id, intent["buyer_id"])

        if intent and vault_id and vault_status == "VAULTED":
            encrypted = PaymentService._fernet().encrypt(vault_id.encode()).decode()
            token_hash = hashlib.sha256(vault_id.encode()).hexdigest()
            save_payment_method(
                str(uuid.uuid4()),
                intent["buyer_id"],
                encrypted,
                token_hash,
                {
                    "paypal_customer_id": paypal_customer_id,
                    "merchant_customer_id": merchant_customer_id,
                    "vault_status": vault_status,
                },
            )
            audit(
                "paypal.vault_token_received",
                "payment_order",
                order_id,
                details={"buyer_id": intent["buyer_id"], "vault_status": vault_status},
            )

    @staticmethod
    async def capture_order(order_id: str) -> dict:
        stored = rows(
            "SELECT payload_json FROM payment_orders WHERE paypal_order_id=?",
            (order_id,),
        )
        metadata_id = None
        if stored:
            try:
                metadata_id = json.loads(stored[0].get("payload_json") or "{}").get(
                    "_flowpay_client_metadata_id"
                )
            except (TypeError, ValueError):
                metadata_id = None
        response = await paypal_service.capture_order(
            order_id, client_metadata_id=metadata_id
        )
        PaymentService._persist_capture_result(order_id, response)
        return response

    @staticmethod
    async def reconcile_order(order_id: str) -> dict:
        """Read PayPal's canonical order state after an idempotent capture retry."""
        response = await paypal_service.get_order(order_id)
        PaymentService._persist_capture_result(order_id, response)
        return response

    @staticmethod
    async def refund_capture(capture_id: str) -> dict:
        result = await paypal_service.refund_capture(capture_id)
        audit(
            "paypal.refund_requested",
            "capture",
            capture_id,
            details={"refund_id": result.get("id"), "status": result.get("status")},
        )
        return result

    @staticmethod
    def get_saved_methods(buyer_id: str) -> list[dict]:
        return list_payment_methods(buyer_id)

    @staticmethod
    async def delete_saved_method(buyer_id: str, method_id: str) -> dict:
        record = get_payment_method(method_id, buyer_id)
        if not record:
            raise ValueError("The selected saved PayPal method was not found.")
        try:
            vault_id = (
                PaymentService._fernet()
                .decrypt(record["vault_id_ciphertext"].encode())
                .decode()
            )
        except InvalidToken as exc:
            raise RuntimeError(
                "The saved PayPal token could not be decrypted."
            ) from exc

        result = await paypal_service.delete_payment_token(vault_id)
        delete_payment_method_local(method_id, buyer_id)
        return {"status": "deleted", "method_id": method_id, "paypal": result}

    @staticmethod
    def process_vault_webhook(event_type: str, resource: dict) -> dict:
        vault_id = resource.get("id")
        if not vault_id:
            return {"status": "ignored", "reason": "missing_vault_id"}
        token_hash = hashlib.sha256(str(vault_id).encode()).hexdigest()
        if event_type in {
            "VAULT.PAYMENT-TOKEN.DELETED",
            "VAULT.PAYMENT-TOKEN.DELETION-INITIATED",
        }:
            changed = set_payment_method_status_by_hash(
                token_hash,
                "DELETED" if event_type.endswith(".DELETED") else "DELETION_PENDING",
            )
            return {
                "status": "processed" if changed else "unmatched",
                "event_type": event_type,
            }

        if event_type == "VAULT.PAYMENT-TOKEN.CREATED":
            customer = resource.get("customer") or {}
            paypal_customer_id = customer.get("id")
            buyer_id = customer.get(
                "merchant_customer_id"
            ) or get_buyer_for_paypal_customer(paypal_customer_id)
            if not buyer_id or not has_vault_opt_in_for_buyer(buyer_id):
                return {"status": "unmatched", "event_type": event_type}
            encrypted = (
                PaymentService._fernet().encrypt(str(vault_id).encode()).decode()
            )
            save_payment_method(
                str(uuid.uuid4()),
                buyer_id,
                encrypted,
                token_hash,
                {
                    "paypal_customer_id": paypal_customer_id,
                    "vault_status": "VAULTED",
                    "source": "webhook",
                },
            )
            return {"status": "saved", "event_type": event_type}

        return {"status": "received", "event_type": event_type}


payment_service = PaymentService()

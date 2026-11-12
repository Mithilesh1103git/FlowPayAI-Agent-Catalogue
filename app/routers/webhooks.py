import html
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from app.services.paypal_client import paypal_service
from backend.database.sqlite import (
    audit,
    find_order_id_for_capture,
    mark_webhook_status,
    record_webhook,
    save_payment_refund,
    update_payment_status,
    update_refund_status,
)
from backend.services.payment_service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paypal", tags=["PayPal Webhooks & Callbacks"])


def _capture_outcome(capture_data: dict) -> dict:
    captures = (
        capture_data.get("purchase_units", [{}])[0]
        .get("payments", {})
        .get("captures", [])
    )
    capture = captures[0] if captures else {}
    capture_status = capture.get("status") or capture_data.get("status")
    reason = (capture.get("status_details") or {}).get("reason")

    if capture_status == "COMPLETED":
        return {
            "capture_status": "COMPLETED",
            "capture_reason": reason,
            "fulfillment_status": "ready_to_fulfill",
            "fulfillment_allowed": True,
        }

    if capture_status == "PENDING" or reason == "PENDING_REVIEW":
        return {
            "capture_status": "PENDING",
            "capture_reason": reason or "PENDING_REVIEW",
            "fulfillment_status": "pending_review",
            "fulfillment_allowed": False,
        }

    return {
        "capture_status": capture_status or "UNKNOWN",
        "capture_reason": reason,
        "fulfillment_status": "not_ready",
        "fulfillment_allowed": False,
    }


def _capture_event_order_id(resource: dict) -> Optional[str]:
    related_ids = resource.get("supplementary_data", {}).get("related_ids", {})
    return related_ids.get("order_id")


@router.get("/return")
async def paypal_return(
    token: str = Query(..., description="PayPal Order ID passed as ?token=..."),
    payer_id: Optional[str] = Query(None, alias="PayerID"),
):
    order_data = await paypal_service.get_order(order_id=token)
    captures = (
        order_data.get("purchase_units", [{}])[0]
        .get("payments", {})
        .get("captures", [])
    )
    capture = captures[0] if captures else {}
    capture_id = capture.get("id")
    order_status = order_data.get("status")
    capture_status = capture.get("status") or order_status
    capture_reason = (capture.get("status_details") or {}).get("reason")
    is_completed = capture_status == "COMPLETED"
    is_pending_review = (
        capture_status == "PENDING" or capture_reason == "PENDING_REVIEW"
    )
    display_status = (
        "Payment completed"
        if is_completed
        else "Payment pending review" if is_pending_review else "Payment processing"
    )
    message = (
        "Your payment was captured successfully."
        if is_completed
        else (
            "PayPal is reviewing the capture. Do not fulfill this order yet."
            if is_pending_review
            else "PayPal approved the payment. Capture is being completed by the payment service."
        )
    )

    return HTMLResponse(
        content=f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{html.escape(display_status)}</title>
            <style>
              body {{ font-family: system-ui, sans-serif; margin: 3rem auto; max-width: 40rem; padding: 0 1rem; color: #172033; }}
              main {{ border: 1px solid #d8dee9; border-radius: 12px; padding: 2rem; }}
              h1 {{ margin-top: 0; }}
              .status {{ color: {"#087f5b" if is_completed else "#9a6700"}; font-weight: 700; }}
              dt {{ color: #596579; margin-top: 1rem; }}
              dd {{ margin: .25rem 0 0; font-family: ui-monospace, monospace; overflow-wrap: anywhere; }}
                            button {{ background: #1769aa; border: 0; border-radius: 6px; color: white; cursor: pointer; font-size: 1rem; padding: .7rem 1rem; }}
            </style>
          </head>
          <body>
            <main>
              <h1 class="status">{html.escape(display_status)}</h1>
              <p>{html.escape(message)}</p>
              <dl>
                <dt>PayPal order</dt>
                <dd>{html.escape(token)}</dd>
                <dt>PayPal status</dt>
                <dd>{html.escape(str(capture_status))}</dd>
                <dt>Capture ID</dt>
                <dd>{html.escape(str(capture_id or "Not available yet"))}</dd>
              </dl>
                            <p>Refresh this page after the PayPal webhook finishes processing.</p>
                              <button type="button" onclick="window.location.href = window.location.pathname + window.location.search + '&refresh=' + Date.now()">Refresh status</button>
            </main>
          </body>
        </html>
        """,
        status_code=status.HTTP_200_OK,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.get("/cancel")
async def paypal_cancel(token: Optional[str] = Query(None)):
    return {
        "status": "cancelled",
        "order_id": token,
        "message": "User closed or cancelled the PayPal session.",
    }


@router.post("/webhook")
async def paypal_webhook(
    request: Request,
    paypal_auth_algo: Optional[str] = Header(None, alias="paypal-auth-algo"),
    paypal_cert_url: Optional[str] = Header(None, alias="paypal-cert-url"),
    paypal_transmission_id: Optional[str] = Header(
        None, alias="paypal-transmission-id"
    ),
    paypal_transmission_sig: Optional[str] = Header(
        None, alias="paypal-transmission-sig"
    ),
    paypal_transmission_time: Optional[str] = Header(
        None, alias="paypal-transmission-time"
    ),
):
    event_data = await request.json()
    event_type = event_data.get("event_type")
    resource = event_data.get("resource", {})
    order_id = resource.get("id")
    logger.info(
        "PayPal webhook received: event_type=%s order_id=%s",
        event_type,
        order_id,
    )
    sig_headers = {
        "paypal-auth-algo": paypal_auth_algo or "",
        "paypal-cert-url": paypal_cert_url or "",
        "paypal-transmission-id": paypal_transmission_id or "",
        "paypal-transmission-sig": paypal_transmission_sig or "",
        "paypal-transmission-time": paypal_transmission_time or "",
    }

    is_valid = await paypal_service.verify_webhook_signature(event_data, sig_headers)
    if not is_valid:
        logger.warning(
            "PayPal webhook signature rejected: event_type=%s order_id=%s",
            event_type,
            order_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PayPal webhook signature",
        )

    logger.info(
        "PayPal webhook signature verified: event_type=%s order_id=%s",
        event_type,
        order_id,
    )
    event_id = event_data.get("id")
    if isinstance(event_id, str) and event_id:
        inserted = record_webhook(event_id, event_type or "UNKNOWN", True, event_data)
        if not inserted:
            return {"status": "duplicate_ignored", "event_id": event_id}

    async def process_verified_event():
        nonlocal order_id
        if event_type in {
            "VAULT.PAYMENT-TOKEN.CREATED",
            "VAULT.PAYMENT-TOKEN.DELETED",
            "VAULT.PAYMENT-TOKEN.DELETION-INITIATED",
        }:
            result = PaymentService.process_vault_webhook(event_type, resource)
            return {"status": "received", **result}

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            order_id = _capture_event_order_id(resource)
            logger.info("PayPal capture completed for order %s", order_id)
            if order_id:
                update_payment_status(order_id, "COMPLETED", resource)
                audit(
                    "paypal.capture_completed",
                    "payment_order",
                    order_id,
                    details={"event_id": event_id},
                )
            return {
                "status": "received",
                "capture_status": "COMPLETED",
                "fulfillment_status": "ready_to_fulfill",
                "fulfillment_allowed": True,
                "order_id": order_id,
            }

        if event_type == "PAYMENT.CAPTURE.DENIED":
            order_id = _capture_event_order_id(resource)
            logger.warning("PayPal capture denied for order %s", order_id)
            if order_id:
                update_payment_status(order_id, "DENIED", resource)
                audit(
                    "paypal.capture_denied",
                    "payment_order",
                    order_id,
                    severity="WARNING",
                    details={"event_id": event_id},
                )
            return {
                "status": "received",
                "capture_status": "DENIED",
                "fulfillment_status": "failed",
                "fulfillment_allowed": False,
                "order_id": order_id,
            }

        if event_type.startswith("PAYMENT.REFUND."):
            refund_status = (
                resource.get("status") or event_type.rsplit(".", 1)[-1]
            ).upper()
            amount = resource.get("amount") or {}
            capture_id = resource.get("capture_id") or resource.get(
                "supplementary_data", {}
            ).get("related_ids", {}).get("capture_id")
            refund_id = resource.get("id")
            save_payment_refund(
                refund_id,
                capture_id=capture_id,
                order_id=find_order_id_for_capture(capture_id),
                amount=amount.get("value"),
                currency=amount.get("currency_code"),
                status=refund_status,
                payload=resource,
            )
            audit(
                f"paypal.refund_{refund_status.lower()}",
                "payment_refund",
                refund_id,
                details={"event_id": event_id, "capture_id": capture_id},
            )
            return {
                "status": "received",
                "refund_status": refund_status,
                "refund_id": refund_id,
            }

        if event_type in {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}:
            capture_id = resource.get("id")
            order_id = _capture_event_order_id(resource) or find_order_id_for_capture(
                capture_id
            )
            refund_status = (
                "REFUNDED" if event_type.endswith(".REFUNDED") else "REVERSED"
            )
            if refund_status == "REFUNDED":
                changed = update_refund_status(
                    capture_id=capture_id, status="COMPLETED", payload=resource
                )
                if not changed:
                    save_payment_refund(
                        None,
                        capture_id=capture_id,
                        order_id=order_id,
                        status="COMPLETED",
                        payload=resource,
                    )
            if order_id:
                audit(
                    f"paypal.capture_{refund_status.lower()}",
                    "payment_order",
                    order_id,
                    details={"event_id": event_id, "capture_id": capture_id},
                )
            return {
                "status": "received",
                "capture_status": refund_status,
                "fulfillment_status": "not_ready",
                "fulfillment_allowed": False,
                "order_id": order_id,
            }

        if event_type == "PAYMENT.CAPTURE.PENDING":
            order_id = _capture_event_order_id(resource)
            logger.info("PayPal capture pending for order %s", order_id)
            if order_id:
                update_payment_status(order_id, "PENDING", resource)
                audit(
                    "paypal.capture_pending",
                    "payment_order",
                    order_id,
                    details={"event_id": event_id},
                )
            return {
                "status": "received",
                "capture_status": "PENDING",
                "capture_reason": "PENDING_REVIEW",
                "fulfillment_status": "pending_review",
                "fulfillment_allowed": False,
                "order_id": order_id,
            }

        if event_type != "CHECKOUT.ORDER.APPROVED":
            logger.info("Ignoring PayPal event type %s", event_type)
            return {"status": "received", "capture_status": "ignored"}

        resource_status = resource.get("status")
        if resource_status != "APPROVED":
            logger.info(
                "Skipping capture for order %s with resource status %s",
                order_id,
                resource_status,
            )
            return {
                "status": "received",
                "capture_status": "skipped",
                "order_id": order_id,
            }

        if not isinstance(order_id, str) or not order_id.strip():
            logger.error("PayPal approval event did not contain an order ID")
            return {
                "status": "received",
                "capture_status": "failed",
                "message": "Missing PayPal order ID",
            }

        logger.info("Calling PayPal capture API for order %s", order_id)
        try:
            capture_data = await PaymentService.capture_order(order_id)
            outcome = _capture_outcome(capture_data)
            logger.info(
                "PayPal order %s capture status=%s fulfillment_status=%s",
                order_id,
                outcome["capture_status"],
                outcome["fulfillment_status"],
            )
            return {
                "status": "received",
                "order_id": order_id,
                **outcome,
            }
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            issues = {
                item.get("issue")
                for item in detail.get("details", [])
                if isinstance(item, dict)
            }
            if "ORDER_ALREADY_CAPTURED" in issues:
                logger.info(
                    "PayPal order %s was already captured; reconciling status", order_id
                )
                reconciled = await PaymentService.reconcile_order(order_id)
                outcome = _capture_outcome(reconciled)
                return {
                    "status": "received",
                    "order_id": order_id,
                    **outcome,
                }
            if "TRANSACTION_REFUSED" in issues:
                update_payment_status(order_id, "DENIED", detail)
                audit(
                    "paypal.capture_denied",
                    "payment_order",
                    order_id,
                    severity="WARNING",
                    details={
                        "debug_id": detail.get("debug_id"),
                        "reason": "TRANSACTION_REFUSED",
                    },
                )
                logger.warning(
                    "PayPal refused capture for order %s (debug_id=%s)",
                    order_id,
                    detail.get("debug_id"),
                )
                return {
                    "status": "received",
                    "capture_status": "DENIED",
                    "capture_reason": "TRANSACTION_REFUSED",
                    "fulfillment_status": "failed",
                    "fulfillment_allowed": False,
                    "order_id": order_id,
                    "paypal_debug_id": detail.get("debug_id"),
                }
            logger.error(
                "PayPal capture failed for order %s: %s",
                order_id,
                exc.detail,
            )
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        except Exception as exc:
            logger.exception("Unexpected PayPal capture failure for order %s", order_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected PayPal capture failure; webhook may be retried.",
            ) from exc

    try:
        result = await process_verified_event()
    except Exception:
        if isinstance(event_id, str) and event_id:
            mark_webhook_status(event_id, "failed")
        raise
    if isinstance(event_id, str) and event_id:
        mark_webhook_status(event_id, "processed")
    return result

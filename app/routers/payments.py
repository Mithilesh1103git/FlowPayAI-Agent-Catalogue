"""Legacy HTTP adapter retained for compatibility; not mounted by app.main.

The modular-monolith UI calls backend.services.payment_service.PaymentService
directly. FastAPI is reserved for external PayPal callbacks and webhooks.
"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.schemas.app_order import AppOrderInput
from backend.services.payment_service import PaymentService

router = APIRouter(prefix="/orders", tags=["Payments"])


@router.post("/create")
async def create_payment_order(
    order_input: AppOrderInput,
    save_payment_method: bool = False,
    buyer_id: Optional[str] = None,
    saved_method_id: Optional[str] = None,
    paypal_client_metadata_id: Optional[str] = Header(
        None, alias="PayPal-Client-Metadata-Id"
    ),
):
    if (save_payment_method or saved_method_id) and not buyer_id:
        raise HTTPException(
            status_code=400, detail="buyer_id is required for vault operations."
        )
    return await PaymentService.create_order_from_checkout(
        order_input.model_dump(mode="json"),
        buyer_id=buyer_id or "api-anonymous",
        save_method=save_payment_method,
        saved_method_id=saved_method_id,
        client_metadata_id=paypal_client_metadata_id,
    )


@router.post("/refund/{capture_id}")
async def refund_paypal_capture(capture_id: str):
    if not capture_id.strip():
        raise HTTPException(status_code=400, detail="capture_id is required")
    refund_data = await PaymentService.refund_capture(capture_id.strip())
    refund_status = refund_data.get("status", "UNKNOWN")
    return {
        "status": "refunded" if refund_status == "COMPLETED" else "refund_processing",
        "refund_status": refund_status,
        "capture_id": capture_id.strip(),
        "refund_id": refund_data.get("id"),
        "raw_response": refund_data,
    }


@router.delete("/saved-methods/{buyer_id}/{method_id}")
async def delete_saved_payment_method(buyer_id: str, method_id: str):
    return await PaymentService.delete_saved_method(buyer_id, method_id)

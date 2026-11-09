"""In-app shopping cart for FlowPayAI on-site checkout.

Rules:
- Single currency only (no mixed USD/INR carts).
- Items must come from current search results (provider-backed records).
- Cart never authorizes payment or places an order.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import urlparse


def _positive_decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal amount") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a finite positive amount")
    return number


def _is_https(url: Any) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme.lower() == "https" and bool(parsed.netloc)


def empty_cart() -> dict[str, Any]:
    return {
        "cart_id": f"cart-{uuid.uuid4().hex[:12]}",
        "currency": None,
        "items": [],
    }


def cart_subtotal(cart: dict[str, Any]) -> Decimal:
    total = Decimal("0.00")
    for item in cart.get("items") or []:
        total += _positive_decimal(item.get("line_total"), "line_total")
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cart_total_quantity(cart: dict[str, Any]) -> int:
    return sum(int(item.get("quantity", 0)) for item in (cart.get("items") or []))


def add_to_cart(
    cart: dict[str, Any],
    product: dict[str, Any],
    quantity: int = 1,
) -> dict[str, Any]:
    """Add or increase a product line. Enforces single-currency rule."""
    if not isinstance(cart, dict):
        raise ValueError("cart must be a dictionary")
    if not isinstance(product, dict):
        raise ValueError("product must be a dictionary")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 1
        or quantity > 99
    ):
        raise ValueError("quantity must be an integer between 1 and 99")

    product_id = product.get("product_id")
    name = product.get("name")
    currency = str(product.get("currency") or "").strip().upper()
    url = product.get("url") or product.get("product_url")
    retailer = (
        product.get("source") or product.get("retailer") or product.get("data_source")
    )
    raw_price = product.get("price")

    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product_id is required")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("product name is required")
    if not currency or len(currency) != 3 or not currency.isalpha():
        raise ValueError("product currency must be a 3-letter code")
    if not _is_https(url):
        raise ValueError("product must have a valid HTTPS URL")
    if not isinstance(retailer, str) or not retailer.strip():
        raise ValueError("product retailer/source is required")

    unit_price = _positive_decimal(raw_price, "price")

    # Single-currency enforcement
    cart_currency = cart.get("currency")
    if cart_currency and cart_currency != currency:
        raise ValueError(
            f"Cart currency is {cart_currency}; cannot add {currency} item. "
            "Clear the cart or choose a matching product."
        )

    items = list(cart.get("items") or [])
    existing = next(
        (i for i in items if i.get("product_id") == product_id.strip()), None
    )

    if existing:
        new_qty = int(existing["quantity"]) + quantity
        if new_qty > 99:
            raise ValueError("quantity per line cannot exceed 99")
        existing["quantity"] = new_qty
        existing["line_total"] = str(
            (unit_price * new_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        # Refresh price/url in case listing changed
        existing["unit_price"] = str(
            unit_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        existing["product_url"] = str(url).strip()
        existing["name"] = name.strip()
        existing["retailer"] = retailer.strip()
    else:
        line_total = (unit_price * quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        items.append(
            {
                "product_id": product_id.strip(),
                "name": name.strip(),
                "retailer": retailer.strip(),
                "product_url": str(url).strip(),
                "quantity": quantity,
                "unit_price": str(
                    unit_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ),
                "line_total": str(line_total),
                "currency": currency,
            }
        )

    return {
        "cart_id": cart.get("cart_id") or f"cart-{uuid.uuid4().hex[:12]}",
        "currency": currency,
        "items": items,
    }


def update_quantity(
    cart: dict[str, Any], product_id: str, quantity: int
) -> dict[str, Any]:
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product_id is required")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
        or quantity > 99
    ):
        raise ValueError(
            "quantity must be an integer between 0 and 99 (0 removes the line)"
        )

    items = list(cart.get("items") or [])
    updated = []
    found = False
    for item in items:
        if item.get("product_id") != product_id.strip():
            updated.append(item)
            continue
        found = True
        if quantity == 0:
            continue  # remove
        unit = _positive_decimal(item.get("unit_price"), "unit_price")
        item = dict(item)
        item["quantity"] = quantity
        item["line_total"] = str(
            (unit * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        updated.append(item)

    if not found:
        raise ValueError(f"product_id {product_id} is not in the cart")

    currency = cart.get("currency") if updated else None
    return {
        "cart_id": cart.get("cart_id") or f"cart-{uuid.uuid4().hex[:12]}",
        "currency": currency,
        "items": updated,
    }


def remove_from_cart(cart: dict[str, Any], product_id: str) -> dict[str, Any]:
    return update_quantity(cart, product_id, 0)


def build_checkout_details(
    cart: dict[str, Any],
    *,
    approval: Optional[dict[str, Any]] = None,
    checkout_intent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the handoff package for the payment team.

    This is confirmation data only. It does not authorize or perform payment.
    """
    if not isinstance(cart, dict):
        raise ValueError("cart must be a dictionary")
    items = cart.get("items") or []
    if not items:
        raise ValueError("cart is empty")

    currency = cart.get("currency")
    if not currency:
        raise ValueError("cart has no currency")

    # Re-validate single currency and totals
    for item in items:
        if item.get("currency") != currency:
            raise ValueError("cart contains mixed currencies")
        if not _is_https(item.get("product_url")):
            raise ValueError(f"item {item.get('product_id')} has no valid HTTPS URL")

    subtotal = cart_subtotal(cart)
    intent_id = checkout_intent_id or f"chk_{uuid.uuid4().hex[:16]}"

    return {
        "schema_version": "1.0",
        "checkout_intent_id": intent_id,
        "cart_id": cart.get("cart_id"),
        "status": "ready_for_payment_team",
        "currency": currency,
        "amount": {
            "value": str(subtotal),
            "currency": currency,
            "minor_units": int(
                (subtotal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            ),
        },
        "items": [dict(item) for item in items],
        "item_count": len(items),
        "total_quantity": cart_total_quantity(cart),
        "source": {
            "provider": "channel3",
            "checkout_mode": "on_site_cart",
        },
        "approval": (
            {
                "decision_id": (approval or {}).get("decision_id"),
                "decision": (approval or {}).get("decision"),
                "purchase_request_id": (approval or {}).get("purchase_request_id"),
            }
            if approval
            else None
        ),
        "policy": {
            "execution_authorized": False,
            "execution_performed": False,
        },
        "notes": [
            "On-site cart confirmation only. Payment is handled by the payment team.",
            "Listing prices are estimates from Channel3 and may change.",
            "FlowPayAI does not place merchant orders or process payment.",
        ],
    }

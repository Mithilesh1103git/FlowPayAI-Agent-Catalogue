from app.schemas.app_order import AppOrderInput


def build_paypal_order_payload(
    app_data: AppOrderInput,
    return_url: str,
    cancel_url: str,
    *,
    save_payment_method: bool = False,
    buyer_id: str | None = None,
    vault_id: str | None = None,
) -> dict:
    """Translate the internal checkout contract into a PayPal Orders v2 payload.

    Vaulting is opt-in. A saved vault token is used only when the buyer
    explicitly selects an already-saved payment method.
    """
    currency = app_data.amount.currency.upper()
    total_val_str = f"{app_data.amount.value:.2f}"

    paypal_items = []
    for item in app_data.items:
        paypal_item = {
            "name": item.name[:127],
            "quantity": str(item.quantity),
            "unit_amount": {
                "currency_code": item.currency.upper(),
                "value": f"{item.unit_price:.2f}",
            },
            "category": "PHYSICAL_GOODS",
            "sku": item.product_id,
        }
        if item.product_url:
            paypal_item["url"] = str(item.product_url)
        paypal_items.append(paypal_item)

    paypal_source: dict = {}
    if vault_id:
        # Pay with a previously vaulted PayPal Wallet.
        paypal_source["vault_id"] = vault_id
    else:
        paypal_source["experience_context"] = {
            "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
            "landing_page": "LOGIN",
            "shipping_preference": "GET_FROM_FILE",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        }
        if save_payment_method:
            if not buyer_id or len(buyer_id) > 64:
                raise ValueError(
                    "buyer_id must contain between 1 and 64 characters when saving a PayPal payment method."
                )
            paypal_source["attributes"] = {
                "customer": {"merchant_customer_id": buyer_id},
                "vault": {
                    "store_in_vault": "ON_SUCCESS",
                    "usage_type": "MERCHANT",
                },
            }

    return {
        "intent": "CAPTURE",
        "payment_source": {"paypal": paypal_source},
        "purchase_units": [
            {
                "reference_id": app_data.cart_id,
                "invoice_id": app_data.checkout_intent_id,
                "amount": {
                    "currency_code": currency,
                    "value": total_val_str,
                    "breakdown": {
                        "item_total": {
                            "currency_code": currency,
                            "value": total_val_str,
                        }
                    },
                },
                "items": paypal_items,
            }
        ],
    }

from __future__ import annotations

import asyncio
import html
import json
import math
import re
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from app.core.config import settings
from backend.services.ecommerce_service import EcommerceService
from backend.services.payment_service import PaymentService
from ecommerce.cart import (
    add_to_cart,
    build_checkout_details,
    cart_subtotal,
    cart_total_quantity,
    empty_cart,
    remove_from_cart,
    update_quantity,
)
from taskworker import TaskWorker

st.image("assets/img/Flow_AI_and_PayPal_Icons_Gradient_Blue.png", width=100)
st.title("FlowPayAI Ecommerce Agent")
st.caption(
    "Multi-agent shopping assistant: plan → research (Channel3) → evaluate → advise. "
    "On-site cart confirmation prepares checkout details. "
    "PayPal operations run through the shared in-process PaymentService."
)

if "shopping_messages" not in st.session_state:
    st.session_state.shopping_messages = []
if "shopping_products" not in st.session_state:
    st.session_state.shopping_products = []
if "shopping_budget_usd" not in st.session_state:
    st.session_state.shopping_budget_usd = None
if "shopping_policy_intent" not in st.session_state:
    st.session_state.shopping_policy_intent = None
if "shopping_policy_error" not in st.session_state:
    st.session_state.shopping_policy_error = None
if "cart" not in st.session_state:
    st.session_state.cart = empty_cart()
if "cart_approval" not in st.session_state:
    st.session_state.cart_approval = None
if "checkout_details" not in st.session_state:
    st.session_state.checkout_details = None
if "paypal_order" not in st.session_state:
    st.session_state.paypal_order = None
if "flowpay_buyer_id" not in st.session_state:
    st.session_state.flowpay_buyer_id = settings.FLOWPAY_DEMO_BUYER_ID

ecommerce_service = EcommerceService()


def extract_usd_budget(prompt: str) -> float | None:
    """Extract a clearly stated USD budget from a shopping prompt.

    This conservative starter parser returns None for unsupported wording.
    It does not authorize purchases.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    patterns = [
        # "maximum total budget is $200", "budget: $1,200", "max budget $200"
        r"(?:maximum|max\.?|budget|spending limit|purchase limit)"
        r"(?:\s+(?:total|spending|purchase))?(?:\s+budget)?"
        r"\s*(?:is|of|:|=)?\s*(?:USD\s*)?\$\s*"
        r"([0-9][0-9,]*(?:\.\d{1,2})?)",
        # "under $200", "up to $1,200"
        r"(?:up to|under|below|less than|not more than)"
        r"\s*(?:USD\s*)?\$\s*"
        r"([0-9][0-9,]*(?:\.\d{1,2})?)",
        # "maximum budget USD 200", "budget: USD 1,200"
        r"(?:maximum|max\.?|budget|spending limit|purchase limit)"
        r"(?:\s+(?:total|spending|purchase))?(?:\s+budget)?"
        r"\s*(?:is|of|:|=)?\s*USD\s+"
        r"([0-9][0-9,]*(?:\.\d{1,2})?)",
        # "under USD 200", "up to USD 1,200"
        r"(?:up to|under|below|less than|not more than)"
        r"\s*USD\s+"
        r"([0-9][0-9,]*(?:\.\d{1,2})?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            amount = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if math.isfinite(amount) and amount > 0:
            return amount

    return None


# Sidebar: E-commerce-only UI
with st.sidebar:
    st.header("Agent")
    st.info("E-commerce Operations")
    st.divider()
    st.subheader("Agent status")
    st.success("E-commerce Operations — Existing agent")
    st.divider()
    confidence = st.slider(
        "Confidence score (for E-commerce testing)",
        min_value=0.0,
        max_value=1.0,
        value=0.85,
        step=0.05,
        help="Passed through for the existing E-commerce agent.",
    )
    if st.button("Start new shopping conversation", use_container_width=True):
        st.session_state.shopping_messages = []
        st.session_state.shopping_products = []
        st.session_state.shopping_budget_usd = None
        st.session_state.shopping_policy_intent = None
        st.session_state.shopping_policy_error = None
        st.session_state.cart = empty_cart()
        st.session_state.cart_approval = None
        st.session_state.checkout_details = None
        st.session_state.paypal_order = None
        st.rerun()


# E-commerce: preserve the existing conversational shopping flow.
st.subheader("Conversational Shopping Assistant")
st.write(
    "Search live shopping results, then ask for a shortlist, product details, "
    "comparisons, or a refined search."
)
with st.expander(
    "Example requests",
    expanded=not bool(st.session_state.shopping_messages),
):
    st.markdown("""
- Find wireless noise-cancelling headphones under $100
- Find gaming laptops under $1,000 with an RTX GPU
- Shortlist the top 3
- Compare the first and third products
- Tell me more about the second product
- Find alternatives under $700
""")

for item in st.session_state.shopping_messages:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item["role"] == "assistant" and item.get("tool_calls"):
            with st.expander("Tool calls and technical details", expanded=False):
                st.json(item["tool_calls"])

# ------------------------------------------------------------------
# Visual search (image + optional text) — Channel3 image_search
# ------------------------------------------------------------------
with st.expander("Visual search (upload a product image)", expanded=False):
    st.caption(
        "Upload a product photo to find similar items on Channel3. "
        "Optionally add text constraints such as budget or color. "
        "Results use the same cart and checkout-details flow as text search."
    )
    uploaded_image = st.file_uploader(
        "Product image",
        type=["png", "jpg", "jpeg", "webp"],
        key="visual_search_upload",
    )
    visual_text = st.text_input(
        "Optional text (budget / features)",
        placeholder="under $100, black, wireless",
        key="visual_search_text",
    )
    if st.button("Search with image", type="primary", use_container_width=True):
        if not uploaded_image:
            st.error("Upload an image first.")
        else:
            import base64
            import re as _re

            raw_bytes = uploaded_image.read()
            image_b64 = base64.b64encode(raw_bytes).decode("ascii")
            max_price = None
            budget_match = _re.search(
                r"(?:under|below|less than|budget(?: of)?|within)\s*\$?\s*"
                r"([0-9][0-9,]*(?:\.[0-9]+)?)",
                visual_text or "",
                _re.I,
            )
            if not budget_match:
                budget_match = _re.search(
                    r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
                    visual_text or "",
                    _re.I,
                )
            if budget_match:
                try:
                    max_price = float(budget_match.group(1).replace(",", ""))
                except ValueError:
                    max_price = None

            try:
                from ecommerce.tools import EcommerceToolRegistry

                tools = EcommerceToolRegistry()
                with st.spinner("Running Channel3 visual search..."):
                    if not hasattr(tools, "search_products_by_image"):
                        st.error(
                            "Image search is not registered in tools. "
                            "Add search_products_by_image or use text search."
                        )
                        image_result = None
                    else:
                        image_result = tools.search_products_by_image(
                            image_base64=image_b64,
                            query=(
                                visual_text.strip()
                                if visual_text and visual_text.strip()
                                else None
                            ),
                            max_price=max_price,
                            limit=10,
                        )
            except Exception as exc:
                st.error(f"Visual search failed: {exc}")
                image_result = None

            if (
                image_result
                and image_result.get("success")
                and image_result.get("products")
            ):
                products = [p for p in image_result["products"] if isinstance(p, dict)]
                st.session_state.shopping_products = products
                st.session_state.shopping_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[Visual search] image uploaded"
                            + (
                                f" · {visual_text.strip()}"
                                if visual_text and visual_text.strip()
                                else ""
                            )
                        ),
                    }
                )
                st.session_state.shopping_messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"Visual search found **{len(products)}** product(s). "
                            "Review them below and add items to the cart when ready."
                        ),
                        "tool_calls": [
                            {
                                "tool": "search_products_by_image",
                                "count": len(products),
                                "search_mode": image_result.get("search_mode", "image"),
                            }
                        ],
                    }
                )
                st.success(f"Found {len(products)} product(s) from the image.")
                st.rerun()
            elif image_result is not None:
                st.error(
                    image_result.get("error")
                    or image_result.get("message")
                    or "No products found for this image."
                )

prompt = st.chat_input("Describe a product or ask a follow-up...")
if prompt:
    # Budget hint for session only (planner inside the graph owns full intent).
    extracted_budget = extract_usd_budget(prompt)
    if extracted_budget is not None:
        st.session_state.shopping_budget_usd = extracted_budget

    previous_history = [
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.shopping_messages
        if item.get("role") in {"user", "assistant"}
    ]
    st.session_state.shopping_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    request = {
        "agent": "ecommerce",
        "payload": {
            "message": prompt,
            "confidence": confidence,
            "conversation_history": previous_history,
            "current_products": st.session_state.shopping_products,
        },
    }
    with st.chat_message("assistant"):
        with st.spinner(
            "Running multi-agent shopping workflow (plan → research → evaluate → advise)..."
        ):
            response = ecommerce_service.search(
                request["payload"]["message"],
                prior_products=request["payload"].get("current_products"),
            )
        answer = (
            response.get("message") or response.get("answer") or "No answer returned."
        )
        response_products = response.get("products")
        structured_products = (
            [item for item in response_products if isinstance(item, dict)]
            if isinstance(response_products, list)
            else []
        )

        if response.get("clarification_needed"):
            st.warning(answer)
        else:
            st.markdown(answer)

        if structured_products:
            st.write(
                "Product results below come from Channel3 via the multi-agent research step. "
                "Decision labels come from the evaluation agent; missing details stay unverified."
            )

        if structured_products:
            import pandas as pd

            table_rows = []
            for idx, product in enumerate(structured_products, start=1):
                price = product.get("price")
                if isinstance(price, (int, float)) and not isinstance(price, bool):
                    price_text = f"{product.get('currency', 'INR')} {price:,.2f}"
                else:
                    price_text = product.get("price_display") or "Not available"
                features = product.get("features") or []
                if isinstance(features, list):
                    feature_text = "; ".join(str(x) for x in features if str(x).strip())
                else:
                    feature_text = str(features).strip()
                url = product.get("url") if isinstance(product.get("url"), str) else ""
                url_type = product.get("url_type", "provider_link")
                link_label = (
                    "Search this product"
                    if url_type == "product_specific_search"
                    else ("Open retailer listing" if url else "Link unavailable")
                )
                checks = product.get("requirement_checks") or []
                supported = [
                    x.get("requirement")
                    for x in checks
                    if x.get("status") == "supported_by_listing"
                ]
                unverified = [
                    x.get("requirement")
                    for x in checks
                    if x.get("status") == "unverified"
                ]
                table_rows.append(
                    {
                        "#": idx,
                        "Product": product.get("name") or "Name unavailable",
                        "Price": price_text,
                        "Retailer": product.get("source") or "Not provided",
                        "Listing evidence status": product.get(
                            "listing_evidence_status", "not_assessed"
                        )
                        .replace("_", " ")
                        .title(),
                        "Features found in listing": "; ".join(
                            str(x) for x in supported
                        )
                        or "None confirmed in listing text",
                        "Unverified requirements": "; ".join(str(x) for x in unverified)
                        or "None / not assessed",
                        "Listing details (as returned)": feature_text
                        or "Not provided by listing",
                        "Rating": (
                            product.get("rating")
                            if product.get("rating") is not None
                            else "Not provided"
                        ),
                        "Reviews": (
                            product.get("reviews")
                            if product.get("reviews") is not None
                            else "Not provided"
                        ),
                        "Link": url,
                        "Link type": link_label,
                    }
                )
            st.dataframe(
                pd.DataFrame(table_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Link": st.column_config.LinkColumn(
                        "Product link",
                        display_text="Open",
                        help="URL associated with this product row.",
                    )
                },
            )
            st.caption(
                "Prices are provider-listed and may change. 'Features found in listing' means the provider's returned text contains that detail; it is not independent merchant verification. Missing specifications remain unverified."
            )
            plan = response.get("shopping_plan")
            if plan:
                with st.expander("Shopping plan (planner agent)", expanded=False):
                    st.json(plan)
            with st.expander("Workflow details", expanded=False):
                st.write(f"**Status:** {response.get('status')}")
                st.write(
                    f"**Qualified:** {len(response.get('qualified_products') or [])}"
                )
                st.write(
                    f"**Shortlisted:** {len(response.get('shortlisted_products') or [])}"
                )
                if response.get("errors"):
                    st.write("**Errors:**")
                    st.json(response.get("errors"))

    if structured_products:
        st.session_state.shopping_products = structured_products
    elif "products" in response and isinstance(response.get("products"), list):
        st.session_state.shopping_products = response.get("products") or []
    st.session_state.shopping_messages.append(
        {
            "role": "assistant",
            "content": answer,
            "tool_calls": [],
            "status": response.get("status"),
            "clarification_needed": bool(response.get("clarification_needed")),
        }
    )

if st.session_state.shopping_products:
    with st.expander(
        f"Current product context ({len(st.session_state.shopping_products)} products)",
        expanded=False,
    ):
        st.dataframe(
            st.session_state.shopping_products,
            use_container_width=True,
            hide_index=True,
        )

    # ------------------------------------------------------------------
    # On-site cart (A + C): multi-item, single currency, checkout details
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("Cart (on-site checkout)")
    st.caption(
        "Add products from the current search results. Single currency only. "
        "Confirming the cart prepares checkout details for the payment service. "
        "PayPal handles the buyer approval and payment capture."
    )

    cart = st.session_state.cart
    selectable_for_cart = [
        p
        for p in st.session_state.shopping_products
        if isinstance(p, dict) and isinstance(p.get("product_id"), str)
    ]

    if selectable_for_cart:

        def _cart_product_label(p: dict) -> str:
            price = p.get("price_display")
            if not price and p.get("price") is not None:
                price = f"{p.get('currency', '')} {p.get('price')}"
            if not price:
                price = "Price n/a"
            source = p.get("source") or p.get("data_source") or "?"
            return f"{p.get('name', 'Product')} — {price} ({source})"

        cart_by_id = {p["product_id"]: p for p in selectable_for_cart}
        with st.form("add_to_cart_form"):
            cart_pid = st.selectbox(
                "Product",
                options=list(cart_by_id.keys()),
                format_func=lambda i: _cart_product_label(cart_by_id[i]),
            )
            cart_qty = st.number_input(
                "Quantity", min_value=1, max_value=99, value=1, step=1
            )
            if st.form_submit_button(
                "Add to cart", type="primary", use_container_width=True
            ):
                try:
                    st.session_state.cart = add_to_cart(
                        cart, cart_by_id[cart_pid], int(cart_qty)
                    )
                    from backend.database.sqlite import save_cart

                    save_cart(
                        st.session_state.cart,
                        st.session_state.get("shopping_session_id"),
                    )
                    st.session_state.cart_approval = None
                    st.session_state.checkout_details = None
                    st.session_state.paypal_order = None
                    st.success("Added to cart.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.info("Search for products first, then add them to the cart.")

    cart = st.session_state.cart
    cart_items = cart.get("items") or []
    if cart_items:
        st.write(
            f"**Cart currency:** {cart.get('currency')} · "
            f"**Lines:** {len(cart_items)} · "
            f"**Units:** {cart_total_quantity(cart)} · "
            f"**Subtotal:** {cart.get('currency')} {cart_subtotal(cart)}"
        )
        for item in cart_items:
            c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
            c1.write(f"**{item.get('name')}**")
            c1.caption(f"{item.get('retailer')} · `{item.get('product_id')}`")
            new_qty = c2.number_input(
                "Qty",
                min_value=0,
                max_value=99,
                value=int(item.get("quantity", 1)),
                key=f"qty_{item.get('product_id')}",
            )
            c3.write(f"{item.get('currency')} {item.get('line_total')}")
            if c4.button("Update", key=f"upd_{item.get('product_id')}"):
                try:
                    st.session_state.cart = update_quantity(
                        cart, item["product_id"], int(new_qty)
                    )
                    from backend.database.sqlite import save_cart

                    save_cart(
                        st.session_state.cart,
                        st.session_state.get("shopping_session_id"),
                    )
                    st.session_state.cart_approval = None
                    st.session_state.checkout_details = None
                    st.session_state.paypal_order = None
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if c4.button("Remove", key=f"rm_{item.get('product_id')}"):
                st.session_state.cart = remove_from_cart(cart, item["product_id"])
                from backend.database.sqlite import save_cart

                save_cart(
                    st.session_state.cart, st.session_state.get("shopping_session_id")
                )
                st.session_state.cart_approval = None
                st.session_state.checkout_details = None
                st.session_state.paypal_order = None
                st.rerun()

        if st.button("Clear cart", use_container_width=True):
            st.session_state.cart = empty_cart()
            from backend.database.sqlite import save_cart

            save_cart(
                st.session_state.cart, st.session_state.get("shopping_session_id")
            )
            st.session_state.cart_approval = None
            st.session_state.checkout_details = None
            st.session_state.paypal_order = None
            st.rerun()

        st.divider()
        st.subheader("Confirm cart (on-site)")
        st.caption(
            "This records your cart confirmation. Payment starts only when you "
            "create a PayPal payment below."
        )
        cart_confirm = st.checkbox(
            "I confirm the products, quantities, and estimated totals in this cart.",
            key="cart_confirm_checkbox",
        )
        if st.button(
            "Confirm cart & build checkout details",
            type="primary",
            use_container_width=True,
        ):
            if not cart_confirm:
                st.error("Please confirm the cart details first.")
            else:
                try:
                    from datetime import datetime, timezone

                    approval = {
                        "decision_id": f"review-{uuid.uuid4().hex}",
                        "decision": "user_approved",
                        "decision_status": "user_approved_pending_system_authorization",
                        "cart_id": cart.get("cart_id"),
                        "execution_authorized": False,
                        "execution_performed": False,
                        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    details = build_checkout_details(cart, approval=approval)
                    st.session_state.cart_approval = approval
                    st.session_state.checkout_details = details
                    from backend.database.sqlite import save_checkout

                    save_checkout(details, cart)
                    st.session_state.paypal_order = None
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    details = st.session_state.get("checkout_details")
    if details:
        st.success("Checkout details ready for the payment service.")
        st.write(f"**Intent ID:** `{details.get('checkout_intent_id')}`")
        st.write(
            f"**Amount:** {details.get('amount', {}).get('currency')} "
            f"{details.get('amount', {}).get('value')} · "
            f"**Items:** {details.get('item_count')} · "
            f"**Units:** {details.get('total_quantity')}"
        )
        st.write("**Execution authorized:** No")
        st.write("**Execution performed:** No")
        payload = json.dumps(details, indent=2, ensure_ascii=False)
        st.download_button(
            "Download checkout details (JSON)",
            data=payload,
            file_name=f"{details.get('checkout_intent_id', 'checkout')}.json",
            mime="application/json",
            use_container_width=True,
        )
        with st.expander("Checkout details JSON", expanded=True):
            st.code(payload, language="json")

        st.divider()
        st.subheader("PayPal checkout")
        st.caption(
            "Payment operations call the shared Python PaymentService directly. "
            "Only the external PayPal approval page and PayPal webhooks cross the network."
        )

        buyer_id = st.session_state.flowpay_buyer_id
        saved_methods = PaymentService.get_saved_methods(buyer_id)
        saved_method_by_id = {item["method_id"]: item for item in saved_methods}

        if (
            saved_methods
            and settings.PAYPAL_VAULT_CHARGES_ENABLED
            and settings.PAYPAL_RDA_ENABLED
        ):
            payment_choice = st.radio(
                "Payment method",
                ["Pay with PayPal", "Use a saved PayPal method"],
                horizontal=True,
                key="paypal_payment_choice",
            )
        else:
            payment_choice = "Pay with PayPal"
            if saved_methods:
                st.info(
                    f"{len(saved_methods)} saved PayPal method(s) exist. "
                    "Using saved tokens is disabled until PayPal FraudNet/Magnes risk-data "
                    "collection, a client risk correlation ID, and merchant approval are configured."
                )
            else:
                st.caption(
                    "No saved PayPal methods are associated with this demo buyer yet."
                )

        save_method = False
        selected_method_id = None

        if payment_choice == "Use a saved PayPal method":
            selected_method_id = st.selectbox(
                "Saved PayPal method",
                options=list(saved_method_by_id.keys()),
                format_func=lambda method_id: (
                    f"PayPal Wallet · saved {saved_method_by_id[method_id]['created_at'][:10]}"
                ),
                key="selected_paypal_vault_method",
            )
            st.caption(
                "PayPal may still request additional approval or authentication. "
                "A saved token does not guarantee a frictionless transaction."
            )
        else:
            vault_key_available = (
                bool(settings.PAYPAL_VAULT_ENCRYPTION_KEY)
                and settings.PAYPAL_VAULT_ENABLED
            )
            save_method = st.checkbox(
                "Save my PayPal payment method for future purchases (optional)",
                value=False,
                disabled=not vault_key_available,
                help=(
                    "If selected, FlowPayAI asks PayPal to vault the wallet after "
                    "a successful payment. This is optional and off by default."
                ),
            )
            if not vault_key_available:
                st.info(
                    "Optional saving is disabled until PayPal Vault is enabled for the merchant app "
                    "and PAYPAL_VAULT_ENCRYPTION_KEY is configured. Ordinary PayPal checkout remains available."
                )

        if st.button("Create PayPal payment", type="primary", use_container_width=True):
            try:
                with st.spinner("Creating PayPal order..."):
                    payment_result = asyncio.run(
                        PaymentService.create_order_from_checkout(
                            details,
                            buyer_id=buyer_id,
                            save_method=save_method,
                            saved_method_id=selected_method_id,
                            client_metadata_id=st.session_state.get(
                                "paypal_client_metadata_id"
                            ),
                        )
                    )
                st.session_state.paypal_order = payment_result
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create PayPal order: {exc}")

        paypal_order = st.session_state.get("paypal_order")
        if paypal_order:
            approval_url = paypal_order.get("approval_url")
            if approval_url:
                st.success(
                    f"PayPal order {paypal_order.get('order_id', 'created')} is ready."
                )
                st.link_button(
                    "Continue to PayPal",
                    approval_url,
                    use_container_width=True,
                )
            elif paypal_order.get("paypal_status") in {"COMPLETED", "APPROVED"}:
                st.success(
                    f"PayPal order {paypal_order.get('order_id')} was created "
                    f"with status {paypal_order.get('paypal_status')}."
                )
            else:
                st.info(
                    "PayPal order created. No approval URL was returned; "
                    f"current status: {paypal_order.get('paypal_status', 'unknown')}."
                )

        if saved_methods:
            with st.expander("Manage saved PayPal methods", expanded=False):
                st.caption(
                    "Removing a saved method deletes its token from PayPal Vault "
                    "and marks it inactive in FlowPayAI."
                )
                method_to_remove = st.selectbox(
                    "Saved method to remove",
                    options=list(saved_method_by_id.keys()),
                    format_func=lambda method_id: (
                        f"PayPal Wallet · saved {saved_method_by_id[method_id]['created_at'][:10]}"
                    ),
                    key="remove_paypal_vault_method",
                )
                if st.button("Remove saved PayPal method", use_container_width=True):
                    try:
                        with st.spinner("Removing saved PayPal method..."):
                            asyncio.run(
                                PaymentService.delete_saved_method(
                                    buyer_id, method_to_remove
                                )
                            )
                        st.success("Saved PayPal method removed.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not remove saved PayPal method: {exc}")

        st.divider()
        st.subheader("PayPal Sandbox refund test")
        st.caption(
            "Enter a completed PayPal capture ID to request a full refund through "
            "the shared PaymentService."
        )
        refund_capture_id = st.text_input(
            "Capture ID",
            placeholder="Enter the capture ID returned by PayPal",
            key="refund_capture_id",
        )
        if st.button("Refund capture", use_container_width=True):
            if not refund_capture_id.strip():
                st.error("Enter a capture ID first.")
            else:
                try:
                    with st.spinner("Requesting PayPal refund..."):
                        refund_result = asyncio.run(
                            PaymentService.refund_capture(refund_capture_id.strip())
                        )
                    refund_status = str(refund_result.get("status") or "UNKNOWN").upper()
                    refund_amount = refund_result.get("amount") or {}
                    refund_id = refund_result.get("id") or "Not supplied by PayPal"
                    status_color = (
                        "#16803c" if refund_status == "COMPLETED"
                        else "#b7791f" if refund_status in {"PENDING", "PROCESSING"}
                        else "#b42318" if refund_status in {"FAILED", "DENIED", "CANCELLED"}
                        else "#475467"
                    )
                    status_message = {
                        "COMPLETED": "The refund has been completed by PayPal.",
                        "PENDING": "PayPal has accepted the refund and is still processing it.",
                        "FAILED": "PayPal could not complete the refund. Review the refund record.",
                    }.get(refund_status, "PayPal returned a refund status. Check PayPal Operations for subsequent updates.")
                    st.markdown(
                        f"""
                        <div style="border:1px solid #d0d5dd;border-radius:12px;padding:16px;margin-top:10px;">
                          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                            <strong style="font-size:1.05rem;">Refund result</strong>
                            <span style="background:{status_color};color:white;padding:5px 10px;border-radius:20px;font-size:.8rem;font-weight:700;">{html.escape(refund_status)}</span>
                          </div>
                          <p style="margin:12px 0;color:inherit;">{html.escape(status_message)}</p>
                          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
                            <div><small style="color:#667085;">Refund amount</small><div><strong>{html.escape(str(refund_amount.get('value') or 'Not supplied'))} {html.escape(str(refund_amount.get('currency_code') or ''))}</strong></div></div>
                            <div><small style="color:#667085;">Refund ID</small><div style="overflow-wrap:anywhere;"><strong>{html.escape(str(refund_id))}</strong></div></div>
                            <div><small style="color:#667085;">Capture ID</small><div style="overflow-wrap:anywhere;"><strong>{html.escape(refund_capture_id.strip())}</strong></div></div>
                          </div>
                          <p style="margin:12px 0 0;color:#667085;font-size:.82rem;">Track subsequent status changes in PayPal Operations → Refund activity.</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                except Exception as exc:
                    st.error(f"PayPal refund failed: {exc}")

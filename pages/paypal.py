import asyncio

import pandas as pd
import streamlit as st

from backend.database.sqlite import rows
from backend.services.payment_service import PaymentService
from components.aggrid import render_grid

st.image("assets/img/paypal-logo-2.png", width=100)
st.title("Payment Operations")
st.caption(
    "Monitor PayPal payments and refunds, reconcile pending transactions, "
    "and review the complete transaction history."
)

TERMINAL_PAYMENT_STATUSES = {
    "COMPLETED",
    "DENIED",
    "FAILED",
    "CANCELLED",
    "VOIDED",
    "REFUNDED",
    "REVERSED",
}
TERMINAL_REFUND_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "DENIED"}


def load_payment_orders():
    return rows("""
        SELECT paypal_order_id,checkout_id,amount,currency,status,created_at
        FROM payment_orders
        ORDER BY created_at DESC
        LIMIT 1000
        """)


def load_refunds():
    return rows("""
        SELECT refund_id,capture_id,paypal_order_id,amount,currency,status,created_at,updated_at
        FROM payment_refunds
        ORDER BY updated_at DESC
        LIMIT 1000
        """)


data = load_payment_orders()
refund_data = load_refunds()

pending_orders = [
    item
    for item in data
    if str(item.get("status") or "").upper() not in TERMINAL_PAYMENT_STATUSES
]
pending_refunds = [
    item
    for item in refund_data
    if str(item.get("status") or "").upper() not in TERMINAL_REFUND_STATUSES
]

st.subheader("Payment transactions")
st.caption(
    "Unified transaction history. Payments and refunds appear as separate entries; "
    "refund amounts are shown as negative values and linked to their original capture."
)

if st.button(
    "Check pending transaction status",
    type="primary",
    use_container_width=True,
    disabled=not pending_orders and not pending_refunds,
):
    orders_to_check = pending_orders[:50]
    refunds_to_check = [
        item
        for item in pending_refunds
        if item.get("refund_id") and not str(item["refund_id"]).startswith("capture:")
    ][:50]
    total_to_check = len(orders_to_check) + len(refunds_to_check)
    checked_payments = 0
    checked_refunds = 0
    failures = []

    if total_to_check == 0:
        st.info(
            "There are no pending PayPal records with IDs available for status verification."
        )
    else:
        progress = st.progress(0, text="Checking pending PayPal transactions...")
        completed_checks = 0

        for order in orders_to_check:
            order_id = order["paypal_order_id"]
            try:
                asyncio.run(PaymentService.reconcile_order(order_id))
                checked_payments += 1
            except Exception as exc:
                failures.append(f"Payment {order_id}: {exc}")
            completed_checks += 1
            progress.progress(
                completed_checks / total_to_check,
                text=f"Checked {completed_checks} of {total_to_check} transactions",
            )

        for refund in refunds_to_check:
            refund_id = refund["refund_id"]
            try:
                asyncio.run(PaymentService.reconcile_refund(refund_id))
                checked_refunds += 1
            except Exception as exc:
                failures.append(f"Refund {refund_id}: {exc}")
            completed_checks += 1
            progress.progress(
                completed_checks / total_to_check,
                text=f"Checked {completed_checks} of {total_to_check} transactions",
            )

        progress.empty()
        data = load_payment_orders()
        refund_data = load_refunds()
        pending_orders = [
            item
            for item in data
            if str(item.get("status") or "").upper() not in TERMINAL_PAYMENT_STATUSES
        ]
        pending_refunds = [
            item
            for item in refund_data
            if str(item.get("status") or "").upper() not in TERMINAL_REFUND_STATUSES
        ]
        st.success(
            f"Checked {checked_payments} payment(s) and "
            f"{checked_refunds} refund(s) against PayPal."
        )
        if failures:
            st.warning(
                "Some transactions could not be refreshed. Their previously stored "
                "statuses were left unchanged."
            )
            for failure in failures:
                st.caption(failure)
        st.caption(
            f"{len(pending_orders)} payment(s) and {len(pending_refunds)} refund(s) "
            "still have a non-terminal status."
        )

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Recorded payment orders", len(data))
metric_col2.metric(
    "Awaiting status",
    len(pending_orders) + len(pending_refunds),
)
metric_col3.metric("Recorded refunds", len(refund_data))

payment_ledger = []
for item in data:
    payment_ledger.append(
        {
            "Type": "Payment",
            "Transaction ID": item.get("paypal_order_id"),
            "Related Capture ID": None,
            "Order ID": item.get("paypal_order_id"),
            "Checkout ID": item.get("checkout_id"),
            "Amount": pd.to_numeric(item.get("amount"), errors="coerce"),
            "Currency": item.get("currency"),
            "Status": item.get("status"),
            "Created At": item.get("created_at"),
            "Updated At": None,
        }
    )

refund_ledger = []
for item in refund_data:
    amount = pd.to_numeric(item.get("amount"), errors="coerce")
    refund_ledger.append(
        {
            "Type": "Refund",
            "Transaction ID": item.get("refund_id"),
            "Related Capture ID": item.get("capture_id"),
            "Order ID": item.get("paypal_order_id"),
            "Checkout ID": None,
            "Amount": -abs(amount) if pd.notna(amount) else amount,
            "Currency": item.get("currency"),
            "Status": item.get("status"),
            "Created At": item.get("created_at"),
            "Updated At": item.get("updated_at"),
        }
    )

ledger_data = payment_ledger + refund_ledger
ledger_df = pd.DataFrame(
    ledger_data,
    columns=[
        "Type",
        "Transaction ID",
        "Related Capture ID",
        "Order ID",
        "Checkout ID",
        "Amount",
        "Currency",
        "Status",
        "Created At",
        "Updated At",
    ],
)
if not ledger_df.empty:
    ledger_df["_sort_at"] = ledger_df["Updated At"].fillna(ledger_df["Created At"])
    ledger_df = (
        ledger_df.sort_values("_sort_at", ascending=False, na_position="last")
        .drop(columns=["_sort_at"])
        .reset_index(drop=True)
    )

render_grid(ledger_df, key="paypal-unified-transactions", height=500)

st.divider()
st.subheader("Refund activity")
st.caption(
    "Detailed refund records and their latest statuses. Refunds remain separate "
    "from the original payment capture."
)
refund_metric1, refund_metric2 = st.columns(2)
refund_metric1.metric("Refunds awaiting final status", len(pending_refunds))
refund_metric2.metric(
    "Completed refunds",
    sum(
        1
        for item in refund_data
        if str(item.get("status") or "").upper() == "COMPLETED"
    ),
)
render_grid(pd.DataFrame(refund_data), key="paypal-refunds", height=340)
st.caption(
    "Refund API responses and verified PayPal refund webhooks update these records. "
    "Use **Check pending transaction status** above to reconcile pending payments "
    "and refunds with PayPal."
)

import pandas as pd
import streamlit as st

from backend.database.sqlite import rows
from components.aggrid import render_grid

st.title("PayPal Operations")
st.caption(
    "Payment order records persisted by the application. Streamlit payment actions use the shared in-process PaymentService; FastAPI only receives PayPal callbacks and webhooks."
)
data = rows(
    "SELECT paypal_order_id,checkout_id,amount,currency,status,created_at FROM payment_orders ORDER BY created_at DESC LIMIT 1000"
)
st.metric("Recorded payment orders", len(data))
render_grid(pd.DataFrame(data), key="paypal-orders", height=460)
st.info(
    "Orders created through the E-commerce checkout and shared PaymentService are shown here. Configure PayPal Sandbox credentials and a public webhook URL before testing live callbacks."
)

import pandas as pd
import streamlit as st

from backend.services.dashboard_service import metrics
from components.aggrid import render_grid

st.image("assets/img/FlowPay_AI_PayPal_Integration_Banner_Contrast_Grey.png", width=300)
st.title("Dashboard")
st.caption(
    "An overview of workflow activity, product discovery, payments, and audit events."
)
m = metrics()
cols = st.columns(4)
for col, label, value in zip(
    cols,
    ["Workflow runs", "Products indexed", "Payment orders", "Audit events"],
    [m["workflows"], m["products"], m["payments"], m["audit_events"]],
):
    col.metric(label, value)
left, right = st.columns(2)
with left:
    st.subheader("Workflow status")
    render_grid(pd.DataFrame(m["workflow_status"]), key="workflow-status", height=220)
with right:
    st.subheader("Payment status")
    render_grid(pd.DataFrame(m["payment_status"]), key="payment-status", height=220)
st.subheader("Recent workflow executions")
render_grid(pd.DataFrame(m["recent"]), key="recent-workflows", height=360)

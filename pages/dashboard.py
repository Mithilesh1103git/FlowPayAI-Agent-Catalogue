import pandas as pd
import streamlit as st

from backend.database.duckdb import query, refresh
from backend.services.dashboard_service import metrics
from components.aggrid import render_grid

st.title("FlowPayAI Dashboard")
st.caption(
    "Operational overview from persisted SQLite records; DuckDB provides optional analytical queries."
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
with st.expander("Refresh DuckDB analytical snapshot"):
    if st.button("Refresh analytics"):
        try:
            refresh()
            st.success("DuckDB snapshot refreshed.")
        except Exception as e:
            st.error(f"Analytics refresh failed: {e}")
    st.caption(
        "DuckDB is an analytical read model. SQLite remains the operational source of truth."
    )

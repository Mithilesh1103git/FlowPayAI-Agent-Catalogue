import json

import pandas as pd
import streamlit as st

from backend.services.audit_service import list_events
from components.aggrid import render_grid

st.title("Audit & Reports")
st.caption(
    "Append-only application event history. This is an application audit trail, not a certified compliance ledger."
)
limit = st.selectbox("Records", [100, 250, 500, 1000], index=2)
data = list_events(limit)
df = pd.DataFrame(data)
if not df.empty:
    for c in ["details_json"]:
        if c in df:
            df[c] = df[c].fillna("{}")
    render_grid(
        df.drop(columns=["details_json"], errors="ignore"),
        key="audit-events",
        height=520,
    )
    st.download_button(
        "Export audit events (CSV)",
        df.to_csv(index=False).encode(),
        "flowpay-audit.csv",
        "text/csv",
    )
    with st.expander("Inspect event details"):
        selected = st.selectbox("Event ID", df["event_id"].tolist())
        row = df[df.event_id == selected].iloc[0]
        st.json(json.loads(row.get("details_json") or "{}"))
else:
    st.info(
        "No audit events yet. Run a shopping workflow or create a payment to populate this page."
    )

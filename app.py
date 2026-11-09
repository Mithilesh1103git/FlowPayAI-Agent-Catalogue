from pathlib import Path

import streamlit as st

from backend.database.sqlite import init_db

init_db()
st.set_page_config(page_title="FlowPayAI", page_icon="💳", layout="wide")
dashboard = st.Page(
    "pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True
)
ecommerce = st.Page(
    "pages/ecommerce.py", title="E-commerce", icon=":material/shopping_cart:"
)
paypal = st.Page(
    "pages/paypal.py", title="PayPal Operations", icon=":material/payments:"
)
audit = st.Page("pages/audit.py", title="Audit & Reports", icon=":material/fact_check:")
pg = st.navigation(
    {
        "Overview": [dashboard],
        "Commerce": [ecommerce],
        "Payments": [paypal],
        "Governance": [audit],
    }
)
pg.run()

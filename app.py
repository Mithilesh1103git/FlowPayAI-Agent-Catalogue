from pathlib import Path

import streamlit as st

from backend.database.sqlite import init_db

init_db()

st.logo(
    "assets/img/Flow_AI_and_PayPal_Icons_Gradient_Blue.png",  # Can be a local file path, URL, or emoji
    size="large",  # Options: "small", "medium", "large"
    link="http://localhost:8501",  # Optional URL when the logo is clicked
    icon_image="assets/img/Flow_AI_and_PayPal_Icons_Gradient_Blue.png",  # Optional smaller image for collapsed sidebar
)

st.set_page_config(
    page_title="FlowPayAI",
    page_icon="assets/img/Flow_AI_and_PayPal_Icons_Gradient_Blue.png",
    layout="wide",
)

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
how_to_doc = st.Page("pages/user_guide.py", title="User Guide", icon=":material/book:")
pg = st.navigation(
    {
        "Home": [dashboard],
        "Agent Catalogue": [ecommerce],
        "PayPal": [paypal],
        "Governance": [audit],
        "Documentation": [how_to_doc],
    }
)
pg.run()

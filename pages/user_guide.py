import streamlit as st

st.title("FlowPayAI User Guide")
st.caption(
    "A practical guide to discovering products, completing PayPal Sandbox checkout, "
    "and reviewing application activity."
)

st.markdown(
    """
    ## 1. Start at the Dashboard

    The Dashboard gives you an operational overview of FlowPayAI. It summarizes
    workflow runs, indexed products, payment orders, and audit events. The tables
    show workflow and payment statuses, along with recent workflow executions.

    ## 2. Discover products in Agent Catalogue

    1. Open **Agent Catalogue** from the sidebar.
    2. Enter a natural-language shopping request describing what you need.
    3. Run the shopping workflow.
    4. Review the products returned by the workflow, including their available
       details and evaluation/recommendation information.
    5. Add the products you want to the on-site cart.

    The shopping workflow uses specialized AI agents to help with product
    discovery, research, evaluation, and recommendations. Review the results
    before proceeding; AI recommendations are assistance, not a purchase
    authorization.

    ## 3. Prepare checkout

    1. Review the items and quantities in the cart.
    2. Confirm the cart and build the checkout details.
    3. Review the checkout amount and currency.
    4. Continue to the PayPal checkout section.

    This build is configured for the US PayPal Sandbox and USD checkout.
    Checkout details are prepared by the application before a PayPal order is
    created.

    ## 4. Pay with PayPal Sandbox

    1. Choose **Pay with PayPal**.
    2. Optionally select the payment-method saving option only if it is enabled
       and you want to opt in.
    3. Select **Create PayPal payment**.
    4. When the order is created, select **Continue to PayPal**.
    5. Sign in using the PayPal Sandbox buyer account and approve or cancel the
       payment on PayPal.
    6. After approval, PayPal sends the browser back to the application and
       sends payment events to the configured webhook endpoint.

    Use your Sandbox buyer credentials for the buyer experience. Do not use a
    real PayPal account for Sandbox testing. The application does not automate
    the buyer's PayPal sign-in or approval.

    ## 5. Check whether a transaction completed

    1. Open **PayPal Operations** from the sidebar.
    2. Find the order in the payment transactions table.
    3. Select **Check pending transaction status** to ask PayPal for the latest
       state of pending payments and refunds.
    4. Review the refreshed status in the table.

    Verified PayPal webhooks also update the stored payment status when events
    arrive. A browser return or an approved order is not, by itself, proof that
    funds were captured. Treat **COMPLETED** as a successful capture; statuses
    such as **CREATED**, **APPROVED**, or **PENDING** are not completed payments.
    Terminal outcomes such as **DENIED**, **REFUNDED**, or **REVERSED** should
    also be reviewed before taking any follow-up action.

    The status check reconciles up to 50 pending payment orders and up to 50 pending
    refunds with PayPal per click. If a check fails because PayPal is
    temporarily unavailable, the existing stored status is retained and can be
    checked again later.

    ## 6. Review refund activity

    1. In the Ecommerce Agent page, open the PayPal Sandbox refund test section.
    2. Enter the PayPal capture ID for a completed capture and select **Refund capture**.
    3. Review the friendly refund result card, including its status, amount, refund ID,
       and capture ID.
    4. Open **PayPal Operations** and review the **Refund activity** table.
    5. Review the refund as a separate negative-value entry in the main **Payment
       transactions** table and in the detailed **Refund activity** table. If it is
       still pending, use **Check pending transaction status** above to retrieve its
       latest status from PayPal. Verified refund webhooks can also update it.

    Refunds are recorded separately from the original capture. The original payment
    remains recorded as a completed capture while the refund has its own status and
    audit history. A pending refund is not the same as a completed refund.

    ## 7. Review audit activity

    Open **Audit & Reports** to inspect recorded application and payment events.
    Use this page to review the activity trail associated with workflows,
    checkout, payment updates, and webhook processing.

    ## 8. Understand the main application areas

    | Area | Purpose |
    | --- | --- |
    | Dashboard | Operational metrics and recent workflow activity |
    | Agent Catalogue | Natural-language product discovery and cart preparation |
    | PayPal Operations | Payment order records and PayPal status reconciliation |
    | Audit & Reports | Audit events and operational traceability |
    | User Guide | Instructions for using the application |

    ## Important payment and safety notes

    - PayPal Sandbox is for testing; it does not move real money.
    - Only PayPal-confirmed capture status should be treated as payment completion.
    - AI agents help discover and evaluate products. They do not independently
      authorize or execute financial transactions.
    - Payment operations are handled by the application's PaymentService.
      FastAPI provides the external PayPal webhook and browser callback boundary.
    - Webhook signature verification and event de-duplication protect the
      webhook processing flow.
    - Optional PayPal Vault features are available only when the merchant
      account and application configuration meet PayPal's eligibility and
      configuration requirements.
    """
)

with st.expander("Troubleshooting"):
    st.markdown(
        """
        - **No PayPal approval link:** Check the PayPal Sandbox credentials and
          review the application logs for the order-creation error.
        - **Payment or refund remains pending:** Check that the public webhook URL is
          configured correctly, then use **Check pending transaction status**.
        - **Status check fails:** Confirm PayPal API credentials and network
          connectivity, then retry. The last recorded status is retained.
        - **Vault options are unavailable:** Ordinary PayPal checkout can still
          be used. Vault enrollment and saved-token checkout require separate
          merchant eligibility and configuration.
        """
    )

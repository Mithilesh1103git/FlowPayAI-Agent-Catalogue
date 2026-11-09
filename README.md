# FlowPayAI

AI-assisted commerce and PayPal payment application, organized as a modular monolith.

## Architecture

- Streamlit multipage UI: Dashboard, E-commerce, PayPal Operations, Audit & Reports.
- Existing LangGraph shopping workflow and product decision engine are retained.
- Internal UI actions call Python services directly (no internal REST hop).
- Streamlit calls the shared Python PaymentService directly; FastAPI is retained for external PayPal webhooks and browser callbacks.
- SQLite is the operational source of truth; DuckDB is an optional analytical read model.
- AG Grid dependency is included for richer tabular views; current pages use Streamlit dataframe as a safe baseline.

## LLM provider: Nebius Token Factory

The Planner, Research, and Shopping Advisor agents use LangChain's `ChatOpenAI`
client against Nebius Token Factory's OpenAI-compatible chat-completions API.
They default to `nvidia/Nemotron-3.5-Super-VL`; set `NEBIUS_API_KEY` and, if
needed, override `NEBIUS_BASE_URL` or `NEBIUS_MODEL` in `.env`. Per-agent model
overrides (`PLANNER_MODEL`, `RESEARCH_MODEL`, `COMPARISON_MODEL`,
`ADVISOR_MODEL`) are optional. Evaluation and existing-product filtering remain
deterministic Python logic and do not call an LLM.

The earlier `nvidia/nemotron-3-super-120b-a12b` Serverless model is retired by
Nebius on 2026-11-09; this project therefore uses the provider-named replacement
`nvidia/Nemotron-3.5-Super-VL`. Confirm model availability in your Token Factory
account's live model catalog before deployment.


## PayPal checkout and optional Vault

The Streamlit checkout calls `backend.services.payment_service.PaymentService`
directly. FastAPI routes delegate to that same application service, while the
`/paypal/webhook` endpoint remains externally reachable for PayPal notifications.
No internal Streamlit-to-FastAPI HTTP hop or `PAYMENT_SERVICE_URL` is used.

Normal PayPal checkout is always available and does not request Vault enrollment.
The optional **Save my PayPal payment method for future purchases** control is
unchecked by default and is shown only when all of the following are configured:

- `PAYPAL_VAULT_ENABLED=true`
- `PAYPAL_VAULT_ENCRYPTION_KEY` contains a valid Fernet key
- The PayPal Sandbox REST app has Vault enabled
- The merchant account/app has the required PayPal Vault/reference-transaction eligibility

Generate an encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The US PayPal build accepts USD checkout only. The demo uses `FLOWPAY_DEMO_BUYER_ID` as a stable buyer key. Replace this with
the authenticated application's immutable customer ID before multi-user use.
Saved PayPal token IDs are encrypted at rest; the application does not store
PayPal passwords or raw card data.

**Saved-token charges are deliberately disabled by default.** PayPal's current
documentation requires Risk Data Acquisition (RDA) for customer-initiated
transactions using PayPal/Venmo payment tokens, including FraudNet and Magnes
signals. Set `PAYPAL_VAULT_CHARGES_ENABLED=true` and `PAYPAL_RDA_ENABLED=true` only after that client-side
risk-data integration and client-generated correlation-ID propagation have been implemented and tested, and PayPal has approved
the merchant capability. Until then, buyers can opt in to save a method (when
Vault enrollment is enabled), view it, and remove it, but cannot charge it
through the app. A saved token does not guarantee a frictionless checkout.

PayPal Sandbox and production Vault capability must be enabled separately.
The account may require eligibility review for saving PayPal Wallets and
approval for reference transactions. Configure the PayPal webhook in the
Developer Dashboard with at least `CHECKOUT.ORDER.APPROVED`,
`PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`,
`PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REFUNDED`,
`VAULT.PAYMENT-TOKEN.CREATED`, `VAULT.PAYMENT-TOKEN.DELETED`, and
`VAULT.PAYMENT-TOKEN.DELETION-INITIATED`. Set its webhook ID in
`PAYPAL_WEBHOOK_ID` and its public HTTPS URL in `PAYPAL_WEBHOOK_URL`.
See PayPal's current
[Orders API PayPal Vault guide](https://developer.paypal.com/platforms/checkout/save-payment-methods/during-purchase/orders-api/paypal/)
and [saved PayPal information guide](https://developer.paypal.com/checkout/save-customer-info/).

Refunds and captures call the same in-process PaymentService. PayPal webhooks
are signature-verified and deduplicated by PayPal event ID. The buyer return
URL is informational; it is not treated as proof of successful payment.

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill NEBIUS_API_KEY, CHANNEL3_API_KEY and PayPal Sandbox values as needed.
streamlit run app.py
```

Streamlit runs on 8501. Start the FastAPI webhook/callback endpoint separately when testing PayPal:

```bash
uvicorn app.main:app --reload --port 8000
```

There is no internal `PAYMENT_SERVICE_URL`: Streamlit calls `PaymentService` in-process. Run FastAPI only to receive PayPal's external webhooks and browser callbacks; both processes must use the same `FLOWPAY_DB_PATH`.
For local development, set `FLOWPAY_DB_PATH=./data/flowpayai.sqlite3` and
`FLOWPAY_DUCKDB_PATH=./data/flowpayai.duckdb`.

## Docker

```bash
docker build -t flowpayai .
docker run --rm -p 7860:7860 -v flowpay-data:/data --env-file .env flowpayai
```

Nginx exposes Streamlit on port 7860 and proxies the external webhook/callback paths to FastAPI.
Mount `/data` to persistent storage. Do not rely on container filesystem persistence.

## Hugging Face Spaces

Create a Docker Space and push this repository. Space README metadata:

```yaml
---
title: FlowPayAI
emoji: 💳
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---
```

Configure secrets in Space Settings: NEBIUS_API_KEY, CHANNEL3_API_KEY,
PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WEBHOOK_ID, and callback URLs.
Use persistent Space storage mounted at `/data` if available on the selected plan.
PayPal webhooks require a publicly reachable HTTPS URL. Start with Sandbox only.

## Persistence model

Workflow runs, product records and audit events are persisted by the E-commerce service.
Payment orders and status transitions are persisted by the shared PaymentService
and webhook handler. Streamlit calls the service directly; FastAPI exposes only
external PayPal webhook and browser callback routes. DuckDB refresh is manual
from Dashboard in this starter.

## Security and production notes

- `.env` is intentionally excluded; never commit secrets.
- Add authentication and authorization around the Streamlit application and
  PayPal Operations/refund controls before public deployment.
- PayPal webhook signatures are verified; event IDs are persisted, completed
  deliveries are deduplicated, and failed processing attempts can be retried.
- SQLite is suitable for a small single-instance demo. Use a managed transactional DB
  for concurrent production workloads.
- Audit hash chaining is tamper-evident only if writes are controlled; it is not a
  certified compliance ledger.
- Test PayPal Sandbox end-to-end before production.


## Rebuild validation

All Python source files pass syntax compilation and 14 automated tests pass.
The FastAPI callback app imports successfully and exposes the expected webhook
and browser callback routes (no internal `/orders` API is mounted). The Streamlit
UI could not be runtime-smoke-tested in the packaging environment because
Streamlit is not installed there. PayPal Sandbox and browser-driven checkout
still require end-to-end testing with configured credentials.

---
title: FlowPayAI
emoji: 💳
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# FlowPayAI

AI-assisted commerce and PayPal payment application, organized as a modular monolith.

## Architecture

- Streamlit multipage UI: Dashboard, E-commerce, PayPal Operations, Audit & Reports.
- Existing LangGraph shopping workflow and product decision engine are retained.
- Internal UI actions call Python services directly (no internal REST hop).
- FastAPI remains the external HTTP boundary for PayPal webhooks and browser callbacks.
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

Streamlit calls the shared PaymentService directly; there is no internal PAYMENT_SERVICE_URL. Run FastAPI only for externally reachable PayPal webhooks and browser callbacks. Both processes must share FLOWPAY_DB_PATH.
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
Payment orders are persisted by the shared PaymentService. Streamlit and FastAPI delegate payment operations to the shared PaymentService. SQLite stores payment orders, webhook event IDs, and optional encrypted Vault tokens.
DuckDB refresh is manual from Dashboard in this starter.

## Security and production notes

- `.env` is intentionally excluded; never commit secrets.
- Protect administrative/refund endpoints with authentication and authorization before
  exposing them publicly. The original refund route needs an authorization layer.
- PayPal webhook signatures are verified and PayPal event IDs are persisted for deduplication. Capture requests use stable idempotency keys.
- SQLite is suitable for a small single-instance demo. Use a managed transactional DB
  for concurrent production workloads.
- Audit hash chaining is tamper-evident only if writes are controlled; it is not a
  certified compliance ledger.
- Test PayPal Sandbox end-to-end before production.\n

## Rebuild validation

All Python source files pass syntax compilation and 14 automated tests pass.
The FastAPI callback app imports successfully. Streamlit runtime and PayPal
Sandbox checkout still require end-to-end testing with configured credentials.

## Optional PayPal Vault

Normal PayPal checkout does not require Vault. Vault enrollment is an explicit
buyer opt-in, unchecked by default, and requires `PAYPAL_VAULT_ENABLED=true`,
a Fernet key in `PAYPAL_VAULT_ENCRYPTION_KEY`, and PayPal merchant/app eligibility.
Saved-token charges remain disabled unless `PAYPAL_VAULT_CHARGES_ENABLED=true` and `PAYPAL_RDA_ENABLED=true`;
do not enable those flags until PayPal FraudNet/Magnes risk-data collection and client-generated correlation-ID propagation have been implemented and tested. Replace `FLOWPAY_DEMO_BUYER_ID` with the stable
authenticated customer ID before multi-user use.

# FlowPayAI

**AI-powered commerce, intelligent workflow orchestration, and PayPal payment automation.**

FlowPayAI combines multi-agent AI orchestration, intelligent product discovery, shopping workflows, and PayPal payment operations in a unified application.

Users can describe shopping requirements in natural language, receive AI-assisted product recommendations, evaluate alternatives, create shopping carts, and complete payments through PayPal Sandbox.

The platform also provides workflow-oriented capabilities, an agent catalogue, operational dashboards, payment management, and audit information.

## Architecture

FlowPayAI follows a **modular-monolith architecture** with clearly separated application responsibilities.

- **Streamlit Multipage UI:** Dashboard, E-commerce, PayPal Operations, Audit & Reports.
- **AI Orchestration:** LangGraph-based shopping workflow and product decision engine.
- **Internal Application Calls:** UI actions invoke Python services directly without an internal REST API hop.
- **Payment Services:** Streamlit calls the shared Python `PaymentService` directly.
- **FastAPI:** Provides externally accessible PayPal webhook and browser callback endpoints.
- **Operational Persistence:** SQLite acts as the operational source of truth.
- **Analytical Persistence:** DuckDB provides an optional analytical read model.
- **Tabular Visualization:** AG Grid dependency is included for richer tabular views; current pages use Streamlit dataframe components as a safe baseline.

### High-Level Architecture

```text
                         FLOWPAYAI
                             |
                  +----------+----------+
                  |                     |
             Streamlit UI           FastAPI
                  |                     |
          +-------+--------+       +----+------+
          |       |        |       |           |
       Dashboard E-commerce PayPal Ops     Webhooks
                  |        |       |           |
                  |    LangGraph   |      PayPal Events
                  |        |       |           |
                  |     AI Agents  |           |
                  |        |       |           |
                  |     Channel3   |           |
                  |        |       |           |
                  +--------+-------+-----------+
                             |
                       PaymentService
                             |
                        PayPal APIs
                             |
                      PayPal Sandbox
                             |
                       SQLite Database
                             |
                           DuckDB
                    Analytical Read Model
```

Internal Streamlit actions invoke application services directly. FastAPI is not used as an internal payment-service proxy.

## AI and LLM Architecture

### LLM Provider: Nebius Token Factory

FlowPayAI uses **Nebius Token Factory** as its model inference provider.

The configured default model is:

**NVIDIA Nemotron 3 Nano 30B A3B**

Model identifier:

```env
NEBIUS_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
```

The Planner, Research, and Shopping Advisor agents use LangChain's `ChatOpenAI` client against Nebius Token Factory's OpenAI-compatible chat-completions API.

Configure the following environment variables:

```env
NEBIUS_API_KEY=your_nebius_api_key
NEBIUS_BASE_URL=your_nebius_base_url
NEBIUS_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
```

The base URL should match the endpoint provided by your Nebius Token Factory configuration.

Optional per-agent model overrides:

```env
PLANNER_MODEL=
RESEARCH_MODEL=
COMPARISON_MODEL=
ADVISOR_MODEL=
```

If these overrides are not configured, agents use the default model.

### Multi-Agent Workflow

LangGraph coordinates the multi-step shopping workflow through specialized components.

| Component | Responsibility | LLM |
|---|---|---|
| Planner Agent | Interprets natural-language shopping requirements and creates structured plans | Yes |
| Research Agent | Generates research queries and retrieves product information | Yes |
| Evaluation Engine | Evaluates products against requirements and ranks results | No |
| Shopping Advisor Agent | Generates contextual product recommendations | Yes |
| Existing Products Agent | Filters and reuses previously retrieved products | No |

#### Planner Agent

Interprets natural-language shopping requests and extracts:

- Product categories.
- Budget constraints.
- Mandatory requirements.
- User preferences.
- Product specifications.
- Search queries.

#### Research Agent

Converts the shopping plan into product searches and retrieves relevant listings through Channel3.

#### Evaluation Engine

Uses deterministic Python logic to assess product listings against user requirements.

It distinguishes qualified products from partial matches and evaluates available evidence without relying on an additional LLM call.

#### Shopping Advisor Agent

Generates user-facing product recommendations and explanations using the research and evaluation context.

#### Existing Products Agent

Reuses previously retrieved products when users refine their requirements, avoiding unnecessary repeated searches.

### AI Technology Stack

- **Nebius Token Factory:** Model inference platform.
- **NVIDIA Nemotron 3 Nano 30B A3B:** Configured default language model.
- **LangChain:** LLM integration and structured output handling.
- **LangGraph:** Multi-agent workflow orchestration.

## Product Discovery: Channel3

FlowPayAI integrates the **Channel3 SDK** for external product discovery.

The Research Agent uses Channel3 to retrieve product listings based on the shopping plan generated by the Planner Agent.

The product evaluation engine subsequently assesses available product information against user requirements.

Capabilities include:

- Natural-language product searches.
- Product listing retrieval.
- Product comparisons.
- Budget and specification matching.
- Mandatory requirement evaluation.
- Qualified and partial-match classification.
- Context-aware refinement of previous searches.
- AI-generated product recommendations.

Product evaluation is implemented using deterministic Python logic rather than relying exclusively on LLM-generated judgments.

Configure:

```env
CHANNEL3_API_KEY=your_channel3_api_key
```

## PayPal Integration

FlowPayAI integrates the **PayPal Developer Platform using the free PayPal Sandbox environment**.

### PayPal APIs and Developer Tools

| PayPal Tool | Purpose |
|---|---|
| PayPal Orders v2 API | Creates checkout orders from shopping carts |
| PayPal Payments Captures API | Captures buyer-approved payments and supports refunds |
| PayPal REST API OAuth 2.0 | Authenticates the application using PayPal credentials |
| PayPal Webhooks | Receives asynchronous payment notifications |
| PayPal Webhook Signature Verification API | Verifies incoming webhook authenticity |

### Payment Architecture

The Streamlit checkout calls:

```python
backend.services.payment_service.PaymentService
```

directly.

FastAPI routes delegate to the same application service, while the `/paypal/webhook` endpoint remains externally reachable for PayPal notifications.

There is no internal Streamlit-to-FastAPI HTTP hop and no `PAYMENT_SERVICE_URL` configuration.

Normal PayPal checkout is always available and does not require Vault enrollment.

### Demonstrated Payment Lifecycle

The final demonstration covers:

1. Shopping cart creation.
2. PayPal Sandbox order creation.
3. Buyer redirection to PayPal.
4. Explicit buyer approval.
5. Successful payment capture.
6. Transaction-status confirmation.
7. Refund initiation.
8. Successful refund confirmation with the PayPal refund ID.

The demonstration uses PayPal Sandbox transactions rather than real financial transactions.

The final demo also shows a successful refund of the captured **USD 1,359.00**, with the completed refund status and refund ID displayed.

### PayPal Checkout and Optional Vault

The optional **Save my PayPal payment method for future purchases** control is unchecked by default.

It is displayed only when all the following conditions are met:

- `PAYPAL_VAULT_ENABLED=true`
- `PAYPAL_VAULT_ENCRYPTION_KEY` contains a valid Fernet key.
- The PayPal Sandbox REST application has Vault enabled.
- The merchant account/application has the required PayPal Vault and reference-transaction eligibility.

Generate an encryption key using:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The US PayPal build accepts USD checkout only.

The demo uses `FLOWPAY_DEMO_BUYER_ID` as a stable buyer key. Replace this with the authenticated application's immutable customer ID before multi-user use.

Saved PayPal token IDs are encrypted at rest. The application does not store PayPal passwords or raw card data.

**Saved-token charges are deliberately disabled by default.**

PayPal's current documentation requires Risk Data Acquisition (RDA) for customer-initiated transactions using PayPal/Venmo payment tokens, including FraudNet and Magnes signals.

Set:

```env
PAYPAL_VAULT_CHARGES_ENABLED=true
PAYPAL_RDA_ENABLED=true
```

only after the client-side risk-data integration and client-generated correlation-ID propagation have been implemented and tested, and PayPal has approved the merchant capability.

Until then, buyers can opt in to save a payment method when Vault enrollment is enabled, view it, and remove it, but cannot charge it through the application.

A saved token does not guarantee a frictionless checkout.

PayPal Sandbox and production Vault capabilities must be enabled separately. The account may require eligibility review for saving PayPal Wallets and approval for reference transactions.

### PayPal Webhook Configuration

Configure the PayPal webhook in the Developer Dashboard with at least these events:

```text
CHECKOUT.ORDER.APPROVED
PAYMENT.CAPTURE.COMPLETED
PAYMENT.CAPTURE.DENIED
PAYMENT.CAPTURE.PENDING
PAYMENT.CAPTURE.REFUNDED
VAULT.PAYMENT-TOKEN.CREATED
VAULT.PAYMENT-TOKEN.DELETED
VAULT.PAYMENT-TOKEN.DELETION-INITIATED
```

Configure the webhook environment variables:

```env
PAYPAL_WEBHOOK_ID=your_webhook_id
PAYPAL_WEBHOOK_URL=https://your-public-domain/paypal/webhook
```

The buyer return URL is informational and is not treated as proof of successful payment.

Refunds and captures call the same in-process `PaymentService`.

PayPal webhook notifications are signature-verified and deduplicated using PayPal event IDs.

Useful PayPal documentation:

- [Orders API – Save PayPal payment methods during purchase](https://developer.paypal.com/platforms/checkout/save-payment-methods/during-purchase/orders-api/paypal/)
- [Save customer information](https://developer.paypal.com/checkout/save-customer-info/)

## Technology Stack

| Layer | Technology |
|---|---|
| Programming Language | Python |
| Application UI | Streamlit |
| External HTTP Boundary | FastAPI |
| ASGI Server | Uvicorn |
| LLM Provider | Nebius Token Factory |
| AI Model | NVIDIA Nemotron 3 Nano 30B A3B |
| LLM Integration | LangChain |
| Agent Orchestration | LangGraph |
| Product Discovery | Channel3 SDK |
| Payment Platform | PayPal Developer Platform |
| Payment Environment | PayPal Sandbox |
| Operational Database | SQLite |
| Analytical Database | DuckDB |
| Tabular Visualization Dependency | AG Grid |
| Containerization | Docker |
| Reverse Proxy | Nginx |

## Local Setup

### Prerequisites

- Python 3.10 or later, compatible with the project's dependencies.
- pip.
- Nebius Token Factory API key.
- Channel3 API key.
- PayPal Developer account with Sandbox credentials.

### Installation

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\activate
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment configuration:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configure the following values as applicable:

```env
NEBIUS_API_KEY=
NEBIUS_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
NEBIUS_BASE_URL=

CHANNEL3_API_KEY=

PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
PAYPAL_WEBHOOK_URL=
```

Fill in the actual credentials from your respective developer accounts.

### Run Streamlit

```bash
streamlit run app.py
```

The Streamlit application runs on port `8501` by default.

### Run FastAPI

Start the FastAPI webhook and callback endpoint separately when testing PayPal:

```bash
uvicorn app.main:app --reload --port 8000
```

There is no internal `PAYMENT_SERVICE_URL`.

Streamlit calls `PaymentService` in-process. Run FastAPI to receive PayPal's external webhooks and browser callbacks.

Both processes must use the same database configuration.

For local development:

```env
FLOWPAY_DB_PATH=./data/flowpayai.sqlite3
FLOWPAY_DUCKDB_PATH=./data/flowpayai.duckdb
```

## Docker Deployment

Build the image:

```bash
docker build -t flowpayai .
```

Run the container:

```bash
docker run --rm \
  -p 7860:7860 \
  -v flowpay-data:/data \
  --env-file .env \
  flowpayai
```

Nginx exposes Streamlit on port `7860` and proxies the external webhook/callback paths to FastAPI.

Mount `/data` to persistent storage. Do not rely on container filesystem persistence.

## Hugging Face Spaces Deployment

Create a Docker Space and push this repository.

Use the following Space README metadata:

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

Configure the following secrets in Space Settings:

```text
NEBIUS_API_KEY
NEBIUS_MODEL
NEBIUS_BASE_URL
CHANNEL3_API_KEY
PAYPAL_CLIENT_ID
PAYPAL_CLIENT_SECRET
PAYPAL_WEBHOOK_ID
PAYPAL_WEBHOOK_URL
```

Use persistent Space storage mounted at `/data` if available on the selected plan.

PayPal webhooks require a publicly reachable HTTPS URL.

Start with PayPal Sandbox only.

## Persistence Model

SQLite is the operational source of truth.

The persistence responsibilities are:

- **Shopping sessions:** Maintained by the E-commerce service.
- **Workflow executions:** Persisted by the workflow execution layer.
- **Product records:** Stored by the E-commerce service.
- **Payment orders:** Persisted by the shared `PaymentService`.
- **Payment status transitions:** Updated through payment operations and webhook processing.
- **Webhook events:** Persisted with PayPal event IDs for deduplication.
- **Audit events:** Maintained for operational traceability.

DuckDB provides an optional analytical read model for operational dashboards and reporting.

DuckDB refresh is manual from the Dashboard in this starter implementation.

## Security and Production Notes

- `.env` is intentionally excluded from source control. Never commit credentials or API keys.
- Add authentication and authorization around the Streamlit application and PayPal Operations/refund controls before public deployment.
- PayPal webhook signatures are verified before event processing.
- PayPal event IDs are persisted to support deduplication.
- Completed deliveries are deduplicated, and failed processing attempts can be retried.
- SQLite is suitable for a small, single-instance demonstration. Use a managed transactional database for concurrent production workloads.
- Audit hash chaining is tamper-evident only if writes are controlled. It is not a certified compliance ledger.
- PayPal Vault enrollment and saved-token charging require separate eligibility and security considerations.
- Test PayPal Sandbox end-to-end before moving to production.
- Store all API credentials in environment variables or a dedicated secrets manager.

## Rebuild Validation

The current rebuild validation reports:

- All Python source files pass syntax compilation.
- 14 automated tests pass.
- The FastAPI callback application imports successfully.
- Expected webhook and browser callback routes are exposed.
- No internal `/orders` REST API is mounted.
- Streamlit runtime smoke testing was not completed in the packaging environment because Streamlit was not installed there.
- PayPal Sandbox and browser-driven checkout require end-to-end testing with configured credentials.

The final demonstration additionally shows the shopping workflow, product recommendations, PayPal Sandbox checkout, successful payment capture, and successful refund.

## License

Add an OSI-approved open-source license at the repository root before publishing the repository.
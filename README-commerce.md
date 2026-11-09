# FlowPayAI — Multi-agent shopping + on-site checkout handoff (v2)

AI product discovery (LangGraph multi-agent) → cart → PayPal integration.

The Streamlit app calls the shared Python PaymentService directly. PayPal handles buyer approval; FastAPI receives external PayPal webhooks and delegates capture to that same PaymentService.

---

## Architecture (short)

```text
User (Streamlit)
  → TaskWorker
  → LangGraph:
       Planner → Research (Channel3) OR Use-existing (follow-up refine)
              → Evaluation (deterministic)
              → Advisor
  → Cart → PaymentService (in-process) → PayPal approval → FastAPI webhook → PaymentService capture
```

Follow-ups like “from the products you recommended, only keep 1TB…” reuse prior products when possible (no new Channel3 search).

---

## Setup

```bash
cd FlowPayAI_share_v2   # or rename folder to FlowPayAI
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env
```

Set in `.env`:

- `NEBIUS_API_KEY`
- `CHANNEL3_API_KEY`

```bash
streamlit run app.py
```

Run from this folder so imports resolve (`ecommerce.*`).

---

## Package layout

```text
app.py, taskworker.py
ecommerce/
  cart.py
  product_decision_engine.py
  agents/     planner, research, evaluation, advisor, use_existing, model_config
  orchestration/  graph, state, routing
  tools.py, external_search.py, image_search_patch.py
```

**Not included:** `checkout_adapter.py` (old merchant-link path), direct PayPal API calls from Streamlit, mock checkout.

---

## Checkout JSON (payment teammate)

After cart confirm and selecting **Create PayPal payment**:

- `status`: `ready_for_payment_team`
- `checkout_mode`: `on_site_cart`
- `execution_authorized` / `execution_performed`: `false`
- `amount` + `minor_units` + `items[]`

Prices are **Channel3 listing estimates** and may differ from a live retailer page (config/SKU/time).

---

## Test queries

1. `Find wireless headphones under $200 with ANC and 30 hours battery`
2. `Find gaming laptops under $1500 with RTX 4060, 16GB RAM, 144Hz`
3. Same session follow-up: filter prior results (e.g. 1TB SSD only, no new search)

---

## Notes

- Visual search needs `image_search_patch.py` (included).
- Empty recommendations are reduced via evaluation fallback + advisor resilience; some queries may still be limited by Channel3 catalog coverage.


## Nebius Token Factory

Set `NEBIUS_API_KEY` in `.env`. The LLM agents use `NEBIUS_MODEL` (default
`nvidia/Nemotron-3.5-Super-VL`) through the OpenAI-compatible Nebius endpoint
`https://api.tokenfactory.nebius.com/v1/`. Evaluation and existing-product
selection remain deterministic Python components.

## Optional PayPal Vault

Vault enrollment is a buyer choice and is off by default. Configure
`PAYPAL_VAULT_ENABLED=true` and `PAYPAL_VAULT_ENCRYPTION_KEY` only after
enabling Vault in the PayPal Sandbox app and confirming merchant eligibility.
Saved-token checkout remains disabled until PayPal FraudNet/Magnes RDA collection
and client-generated correlation-ID propagation are implemented and verified (`PAYPAL_VAULT_CHARGES_ENABLED=false` and `PAYPAL_RDA_ENABLED=false` by default).

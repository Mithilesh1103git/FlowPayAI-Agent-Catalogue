# FlowPayAI next-version implementation notes

## Architecture decisions

- The application remains a modular monolith.
- Streamlit calls `backend.services.payment_service.PaymentService` static async methods directly.
- FastAPI is mounted only for externally reachable PayPal webhooks and browser return/cancel callbacks.
- The old `app/routers/payments.py` module is retained as an unmounted compatibility adapter; it is not included in `app.main`.
- Both Streamlit and FastAPI use the same SQLite file through `FLOWPAY_DB_PATH`.
- The app is configured for US-market checkout and rejects non-USD PayPal orders.

## Payment flow

1. Streamlit confirms the cart and creates checkout details. This does not authorize payment.
2. Streamlit calls `PaymentService.create_order_from_checkout(...)` directly.
3. `PaymentService` validates the checkout, builds the PayPal Orders v2 payload, and calls `PayPalService`.
4. The buyer follows the PayPal approval URL and approves on PayPal.
5. PayPal sends a signed `CHECKOUT.ORDER.APPROVED` webhook to FastAPI.
6. FastAPI verifies and deduplicates the webhook, then calls `PaymentService.capture_order(...)`.
7. Payment status is persisted in SQLite. Capture completion, denial, pending review and refund events are processed separately.
8. The browser return page is informational; it is not proof of payment.

## Optional PayPal Vault

- Normal PayPal checkout is the default.
- The checkbox to save a PayPal method is unchecked by default.
- Vault enrollment is only available when `PAYPAL_VAULT_ENABLED=true` and a valid Fernet key is configured.
- The merchant must enable Vault in the PayPal Developer app and obtain any PayPal merchant/reference-transaction approval required for PayPal Wallet saving.
- Token IDs are encrypted before persistence; a SHA-256 hash is used for matching deletion webhooks without storing plaintext token IDs.
- Buyers can view/remove their saved method records.
- Saved-token charges are deliberately disabled unless `PAYPAL_VAULT_CHARGES_ENABLED=true` and `PAYPAL_RDA_ENABLED=true`. Do not turn this on until PayPal FraudNet/Magnes Risk Data Acquisition (RDA) and client-generated correlation-ID propagation are integrated and verified for customer-initiated token transactions.
- `FLOWPAY_DEMO_BUYER_ID` is a stable single-demo identity. Replace it with the authenticated immutable customer ID before exposing the app to multiple buyers.

## Environment configuration

Required for ordinary Sandbox checkout:
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`
- `PAYPAL_WEBHOOK_URL` (public HTTPS callback URL)
- `APP_RETURN_URL`
- `APP_CANCEL_URL`
- `FLOWPAY_DB_PATH`

Optional Vault enrollment:
- `PAYPAL_VAULT_ENABLED=true`
- `PAYPAL_VAULT_ENCRYPTION_KEY=<Fernet key>`

Keep these false until RDA is integrated:
- `PAYPAL_VAULT_CHARGES_ENABLED=false`
- `PAYPAL_RDA_ENABLED=false`

Generate the encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## PayPal Developer Dashboard setup

1. Use a US Sandbox Business merchant and US Sandbox Personal buyer.
2. Enable Accept payments and Vault under the Sandbox REST API app's feature options.
3. Confirm the merchant account has the required eligibility/reference-transaction capability for saving PayPal Wallets.
4. Register the public webhook URL and subscribe to:
   - `CHECKOUT.ORDER.APPROVED`
   - `PAYMENT.CAPTURE.COMPLETED`
   - `PAYMENT.CAPTURE.DENIED`
   - `PAYMENT.CAPTURE.PENDING`
   - `PAYMENT.CAPTURE.REFUNDED`
   - `VAULT.PAYMENT-TOKEN.CREATED`
   - `VAULT.PAYMENT-TOKEN.DELETED`
   - `VAULT.PAYMENT-TOKEN.DELETION-INITIATED`
5. Put the webhook ID and public callback URL in `.env`.

## Validation performed

- Python syntax compilation: passed for all `.py` files.
- Pytest: 14 passed.
- FastAPI import/route smoke test: passed; webhook and callback routes are mounted, internal `/orders` routes are not.
- Streamlit runtime smoke test: not run because Streamlit is not installed in the packaging runtime.
- Live PayPal Sandbox transaction, Vault enrollment, webhook delivery and browser checkout: not tested; they require configured US Sandbox credentials, account eligibility and a public HTTPS callback URL.

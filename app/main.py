from urllib.parse import urlparse

from fastapi import FastAPI

from app.core.config import settings
from app.routers import webhooks
from backend.database.sqlite import init_db

app = FastAPI(
    title="FlowPayAI PayPal Webhooks",
    description="External PayPal webhook and browser callback boundary for the FlowPayAI modular monolith.",
    version="1.0.0",
)

init_db()

app.include_router(webhooks.router)

configured_webhook_path = urlparse(settings.PAYPAL_WEBHOOK_URL).path

if configured_webhook_path != "/paypal/webhook":
    app.add_api_route(
        configured_webhook_path,
        webhooks.paypal_webhook,
        methods=["POST"],
        include_in_schema=False,
    )


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

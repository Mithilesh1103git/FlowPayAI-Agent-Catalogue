from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
PAYPAL_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


class Settings(BaseSettings):
    PAYPAL_CLIENT_ID: str = "mock_client_id"
    PAYPAL_CLIENT_SECRET: str = "mock_client_secret"
    PAYPAL_ENVIRONMENT: Literal["sandbox"] = "sandbox"
    PAYPAL_WEBHOOK_ID: str = "mock_webhook_id"
    PAYPAL_WEBHOOK_URL: str = "http://localhost:8000/paypal/webhook"
    PAYPAL_BASE_URL: str = PAYPAL_SANDBOX_BASE_URL
    PAYPAL_TIMEOUT_SECONDS: int = 15
    PAYPAL_MAX_RETRIES: int = 2
    PAYPAL_VAULT_ENCRYPTION_KEY: str = ""
    PAYPAL_VAULT_ENABLED: bool = False
    PAYPAL_VAULT_CHARGES_ENABLED: bool = False
    PAYPAL_RDA_ENABLED: bool = False
    FLOWPAY_DEMO_BUYER_ID: str = "demo-buyer-001"
    APP_RETURN_URL: str = "https://example.com/paypal/return"
    APP_CANCEL_URL: str = "https://example.com/paypal/cancel"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def set_paypal_base_url(self):
        if self.PAYPAL_BASE_URL.rstrip("/") != PAYPAL_SANDBOX_BASE_URL:
            raise ValueError("PAYPAL_BASE_URL must use the PayPal Sandbox endpoint")
        return self


settings = Settings()

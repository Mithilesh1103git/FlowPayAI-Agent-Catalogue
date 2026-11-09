import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class PayPalService:
    def __init__(self):
        self.base_url = settings.PAYPAL_BASE_URL.rstrip("/")
        self.client_id = settings.PAYPAL_CLIENT_ID
        self.client_secret = settings.PAYPAL_CLIENT_SECRET
        self.webhook_id = settings.PAYPAL_WEBHOOK_ID
        self._client_metadata_ids: Dict[str, str] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=settings.PAYPAL_TIMEOUT_SECONDS,
            transport=httpx.AsyncHTTPTransport(retries=settings.PAYPAL_MAX_RETRIES),
        )

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        res = await client.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
        )
        if res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"PayPal auth failed: {res.text}",
            )
        return res.json()["access_token"]

    async def create_order(
        self,
        payload: dict,
        client_metadata_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._client() as client:
            token = await self.get_access_token(client)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": request_id or str(uuid.uuid4()),
                "Prefer": "return=representation",
            }
            if client_metadata_id:
                headers["PayPal-Client-Metadata-Id"] = client_metadata_id
            res = await client.post(
                f"{self.base_url}/v2/checkout/orders",
                json=payload,
                headers=headers,
            )
            if res.status_code not in (200, 201):
                raise HTTPException(status_code=res.status_code, detail=res.json())
            response_data = res.json()
            order_id = response_data.get("id")
            if client_metadata_id and isinstance(order_id, str):
                self._client_metadata_ids[order_id] = client_metadata_id
            return response_data

    async def capture_order(
        self, order_id: str, client_metadata_id: Optional[str] = None
    ) -> Dict[str, Any]:
        async with self._client() as client:
            token = await self.get_access_token(client)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL, f"flowpayai:paypal:capture:{order_id}"
                    )
                ),
                "Prefer": "return=representation",
            }
            metadata_id = client_metadata_id or self._client_metadata_ids.get(order_id)
            if metadata_id:
                headers["PayPal-Client-Metadata-Id"] = metadata_id
            res = await client.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers=headers,
                json={},
            )
            if res.status_code not in (200, 201):
                raise HTTPException(status_code=res.status_code, detail=res.json())
            return res.json()

    async def get_order(self, order_id: str) -> Dict[str, Any]:
        async with self._client() as client:
            token = await self.get_access_token(client)
            res = await client.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=res.json())
            return res.json()

    async def refund_capture(self, capture_id: str) -> Dict[str, Any]:
        async with self._client() as client:
            token = await self.get_access_token(client)
            response = await client.post(
                f"{self.base_url}/v2/payments/captures/{capture_id}/refund",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "PayPal-Request-Id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL, f"flowpayai:paypal:refund:{capture_id}"
                        )
                    ),
                    "Prefer": "return=representation",
                },
            )
            if response.status_code not in (200, 201, 202):
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json(),
                )
            return response.json()

    async def delete_payment_token(self, vault_id: str) -> Dict[str, Any]:
        async with self._client() as client:
            token = await self.get_access_token(client)
            response = await client.delete(
                f"{self.base_url}/v3/vault/payment-tokens/{vault_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "PayPal-Request-Id": str(uuid.uuid4()),
                },
            )
            if response.status_code not in (200, 204):
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
                raise HTTPException(status_code=response.status_code, detail=detail)
            return {"status": "deleted", "vault_id": vault_id}

    async def verify_webhook_signature(
        self, raw_body: dict, headers: Dict[str, str]
    ) -> bool:
        verification_payload = {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": self.webhook_id,
            "webhook_event": raw_body,
        }
        async with self._client() as client:
            token = await self.get_access_token(client)
            res = await client.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                json=verification_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            if res.status_code != 200:
                return False
            return res.json().get("verification_status") == "SUCCESS"


paypal_service = PayPalService()

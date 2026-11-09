import httpx
import pytest

from app.services.paypal_client import PayPalService


@pytest.mark.asyncio
async def test_client_metadata_id_is_reused_for_capture():
    metadata_headers = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "test-token"})

        metadata_headers.append(request.headers.get("PayPal-Client-Metadata-Id"))
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={"id": "ORDER-123", "status": "CREATED"})

        return httpx.Response(201, json={"id": "ORDER-123", "status": "COMPLETED"})

    service = PayPalService()
    transport = httpx.MockTransport(handle_request)
    service._client = lambda: httpx.AsyncClient(transport=transport)

    await service.create_order(
        {"intent": "CAPTURE"},
        client_metadata_id="client-metadata-123",
    )
    await service.capture_order("ORDER-123")

    assert metadata_headers == ["client-metadata-123", "client-metadata-123"]

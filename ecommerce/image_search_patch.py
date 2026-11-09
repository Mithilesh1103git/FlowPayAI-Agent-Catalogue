"""
Image search helpers for FlowPayAI (Channel3).

Integrate into external_search.py / tools.py / agent.py as documented in
IMAGE_SEARCH_INTEGRATION.md.

Channel3 supports:
  - client.products.image_search(image_url=...)
  - base64 image via API (SDK method names may vary by version)

This module provides a standalone mixin-style implementation you can merge
into ExternalProductSearch, or call from tools directly.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def search_products_by_image(
    *,
    image_url: Optional[str] = None,
    image_base64: Optional[str] = None,
    query: Optional[str] = None,
    features: Optional[list[str]] = None,
    max_price: Optional[float] = None,
    category: Optional[str] = None,
    limit: int = 10,
    channel3_api_key: Optional[str] = None,
    normalize_product_fn=None,
    assess_listing_fn=None,
    rank_products_fn=None,
    resolve_currency_fn=None,
) -> dict[str, Any]:
    """Search Channel3 by image (URL or base64), optionally refined by text.

    Returns the same envelope shape as text search_products().
    """
    api_key = (channel3_api_key or os.getenv("CHANNEL3_API_KEY", "")).strip()
    if not api_key:
        return _failure("CHANNEL3_API_KEY is missing. Configure it in your .env file.")

    has_url = isinstance(image_url, str) and image_url.strip().startswith(
        ("http://", "https://")
    )
    has_b64 = isinstance(image_base64, str) and len(image_base64.strip()) > 100
    if not has_url and not has_b64:
        return _failure("Provide image_url (HTTPS) or image_base64 for visual search.")

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return _failure("limit must be a positive integer.")
    if max_price is not None and (
        isinstance(max_price, bool)
        or not isinstance(max_price, (int, float))
        or max_price < 0
    ):
        return _failure("max_price must be a non-negative number.")

    target_currency = "USD"
    if resolve_currency_fn:
        target_currency = resolve_currency_fn(query)
    elif query:
        text = query.casefold()
        if "₹" in text or re.search(r"\binr\b|\brupees?\b", text):
            target_currency = "INR"
        elif "$" in text or re.search(r"\busd\b|\bdollars?\b", text):
            target_currency = "USD"
        else:
            configured = os.getenv("FLOWPAY_SHOPPING_CURRENCY", "USD").strip().upper()
            if re.fullmatch(r"[A-Z]{3}", configured):
                target_currency = configured

    try:
        from channel3_sdk import Channel3

        client = Channel3(api_key=api_key)
        # Prefer dedicated image_search; fall back to search with image args.
        response = None
        if has_url:
            logger.info(
                "[Channel3] Image search image_url=%s limit=%s", image_url[:80], limit
            )
            try:
                response = client.products.image_search(
                    image_url=image_url.strip(), limit=limit
                )
            except TypeError:
                response = client.products.image_search(image_url=image_url.strip())
            except AttributeError:
                # Older/newer SDK: image on main search
                kwargs = {"image_url": image_url.strip(), "limit": limit}
                if query and query.strip():
                    kwargs["query"] = query.strip()
                response = client.products.search(**kwargs)
        else:
            b64 = image_base64.strip()
            # Strip data-URL prefix if present
            if "," in b64 and b64.lower().startswith("data:"):
                b64 = b64.split(",", 1)[1]
            logger.info(
                "[Channel3] Image search base64 length=%s limit=%s", len(b64), limit
            )
            try:
                response = client.products.image_search(base64_image=b64, limit=limit)
            except TypeError:
                try:
                    response = client.products.image_search(
                        image_base64=b64, limit=limit
                    )
                except Exception:
                    response = client.products.search(base64_image=b64, limit=limit)
            except AttributeError:
                response = client.products.search(base64_image=b64, limit=limit)

        items = _extract_items(response)
        if not isinstance(items, (list, tuple)):
            raise TypeError("Channel3 image search did not return a product list")

    except Exception as exc:
        logger.exception("Channel3 image search failed")
        return _failure(
            f"Channel3 image search failed ({type(exc).__name__}): {exc}",
            providers=["Channel3"],
        )

    requested_features = [
        f for f in (features or []) if isinstance(f, str) and f.strip()
    ]
    if query and query.strip() and not requested_features:
        # light text hint only; ranking still uses features if provided
        pass

    normalized: list[dict[str, Any]] = []
    for item in items:
        if normalize_product_fn:
            product = normalize_product_fn(item, category=category)
        else:
            product = _basic_normalize(item, category=category)
        if not product:
            continue
        if max_price is not None:
            if (product.get("currency") or "").upper() != target_currency:
                continue
            if product.get("price") is None or product["price"] > float(max_price):
                continue
        if assess_listing_fn and requested_features:
            product.update(assess_listing_fn(product, requested_features))
        normalized.append(product)

    if rank_products_fn and requested_features:
        normalized = rank_products_fn(
            normalized,
            requirements=requested_features,
            max_price=max_price,
            target_currency=target_currency if max_price is not None else None,
        )

    return {
        "success": True,
        "count": len(normalized[:limit]),
        "total_matched": len(normalized),
        "products": normalized[:limit],
        "sources_searched": ["Channel3"],
        "search_query": query or "(image search)",
        "data_source": "Channel3",
        "search_mode": "image",
        "target_currency": target_currency,
        "message": (
            None
            if normalized
            else "Channel3 image search returned no usable products after filters."
        ),
    }


def encode_upload_to_base64(file_bytes: bytes) -> str:
    """Encode an uploaded image file to base64 for Channel3."""
    return base64.b64encode(file_bytes).decode("ascii")


def _extract_items(response: Any) -> Any:
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    items = _get(response, "products")
    if items is None:
        items = _get(response, "items")
    if items is None:
        nested = _get(response, "response")
        items = _get(nested, "products") if nested is not None else None
    if items is None:
        data = _get(response, "data")
        items = _get(data, "products") if data is not None else None
    return items


def _basic_normalize(item: Any, *, category: Optional[str]) -> Optional[dict[str, Any]]:
    """Minimal normalizer if full ExternalProductSearch normalizer is not passed in."""

    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    title = str(_get(item, "title", "") or "").strip()
    product_id = str(_get(item, "id", "") or "").strip()
    if not title or not product_id:
        return None
    offers = _get(item, "offers", []) or []
    selected = offers[0] if isinstance(offers, (list, tuple)) and offers else None
    price_obj = _get(selected, "price") if selected is not None else None
    amount = _get(price_obj, "price") if price_obj is not None else None
    currency = str(_get(price_obj, "currency", "") or "").upper() or None
    try:
        price = (
            float(amount)
            if amount is not None and not isinstance(amount, bool)
            else None
        )
    except (TypeError, ValueError):
        price = None
    url = str(_get(selected, "url", "") or "")
    merchant = (
        str(_get(selected, "domain", "") or "Unknown retailer")
        if selected
        else "Unknown retailer"
    )
    return {
        "product_id": f"channel3_{product_id}",
        "name": title,
        "price": price,
        "currency": currency,
        "features": [],
        "category": category or "",
        "rating": None,
        "source": merchant,
        "url": url if url.startswith("https://") else "",
        "price_display": (
            f"{price:,.2f} {currency}"
            if price is not None and currency
            else "Price unavailable"
        ),
        "data_source": "Channel3",
        "channel3_product_id": product_id,
    }


def _failure(message: str, providers: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "success": False,
        "count": 0,
        "total_matched": 0,
        "products": [],
        "sources_searched": providers or [],
        "error": message,
        "data_source": "live_api",
        "search_mode": "image",
    }

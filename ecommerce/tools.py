"""Tool registry for FlowPayAI product discovery.

Text search + image search via Channel3.
"""

from __future__ import annotations

from typing import Any, Optional

from ecommerce.external_search import ExternalProductSearch
from ecommerce.image_search_patch import search_products_by_image as _image_search


class EcommerceToolRegistry:
    """Tools available to the Ecommerce shopping agent."""

    def __init__(self, external_search: Optional[ExternalProductSearch] = None):
        self.external_search = external_search or ExternalProductSearch()
        self._tools = {
            "search_products_multi_source": self.search_products_multi_source,
            "search_products_by_image": self.search_products_by_image,
            "get_external_product": self.get_external_product,
        }

    def search_products_multi_source(
        self,
        query: Optional[str] = None,
        features: Optional[list[str]] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        sources: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return self.external_search.search_products(
            query=query,
            features=features,
            max_price=max_price,
            category=category,
            sources=sources,
            limit=limit,
        )

    def search_products_by_image(
        self,
        image_url: Optional[str] = None,
        image_base64: Optional[str] = None,
        query: Optional[str] = None,
        features: Optional[list[str]] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Visual search via Channel3 (image URL or base64 + optional text filters)."""
        es = self.external_search
        return _image_search(
            image_url=image_url,
            image_base64=image_base64,
            query=query,
            features=features,
            max_price=max_price,
            category=category,
            limit=limit,
            channel3_api_key=getattr(es, "channel3_api_key", None),
            normalize_product_fn=getattr(es, "_normalize_channel3_product", None),
            assess_listing_fn=getattr(es, "_assess_listing_evidence", None),
            resolve_currency_fn=getattr(es, "_resolve_target_currency", None),
        )

    def get_external_product(self, product_id: str) -> dict[str, Any]:
        return self.external_search.get_product_by_id(product_id)

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(tool_name, str):
            return {"success": False, "error": "Tool name must be a string."}

        tool = self._tools.get(tool_name)
        if tool is None:
            return {"success": False, "error": f"Unknown tool: {tool_name}."}

        if not isinstance(arguments, dict):
            return {"success": False, "error": "Tool arguments must be a dictionary."}

        try:
            return tool(**arguments)
        except TypeError:
            return {
                "success": False,
                "error": f"Invalid arguments supplied to tool {tool_name}.",
            }

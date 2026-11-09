"""General-category Channel3 product search for FlowPayAI.

Environment variables:
    CHANNEL3_API_KEY              Channel3 API key (required)
    FLOWPAY_SHOPPING_CURRENCY     Target currency for budget filtering (default: USD)

Results retain the normalized schema used by EcommerceToolRegistry. This module
only discovers products; it does not perform checkout or payment execution.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

from ecommerce.product_decision_engine import rank_products

logger = logging.getLogger(__name__)


class ExternalProductSearch:
    """Search Channel3 for any product category; no SerpApi or Google Shopping fallback."""

    def __init__(self) -> None:
        self.channel3_api_key = os.getenv("CHANNEL3_API_KEY", "").strip()
        self._last_results: dict[str, dict[str, Any]] = {}
        self._last_diagnostics: dict[str, Any] = {}

    def search_products(
        self,
        query: Optional[str] = None,
        features: Optional[list[str]] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        sources: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search Channel3 only and return a normalized product result envelope."""
        error = self._validate_inputs(max_price, limit)
        if error:
            return self._failure(error, providers=[])

        search_query = self._build_query(query, features, max_price, category)
        target_currency = self._resolve_target_currency(query)
        if not search_query:
            return self._failure(
                "Provide a product query, category, or feature to search for.",
                providers=[],
            )
        if not self.channel3_api_key:
            return self._failure(
                "CHANNEL3_API_KEY is missing. Configure it in your .env file.",
                providers=[],
            )

        requested_sources = {
            str(source).strip().casefold()
            for source in (sources or [])
            if isinstance(source, str) and source.strip()
        }
        providers_tried = ["Channel3"]
        try:
            products = self._search_channel3(
                search_query=search_query,
                category=category,
                max_price=max_price,
                target_currency=target_currency,
                requested_sources=requested_sources,
                requested_features=[
                    f for f in (features or []) if isinstance(f, str) and f.strip()
                ],
                limit=limit,
            )
        except Exception as exc:
            logger.exception("Channel3 product search failed")
            return self._failure(
                f"Channel3 product search failed ({type(exc).__name__}). Check the API key, SDK response, and provider status.",
                providers=providers_tried,
            )

        for product in products:
            self._last_results[product["product_id"]] = dict(product)
        if not products:
            return {
                "success": True,
                "count": 0,
                "total_matched": 0,
                "products": [],
                "sources_searched": providers_tried,
                "search_query": search_query,
                "data_source": "Channel3",
                "target_currency": target_currency,
                "diagnostics": dict(self._last_diagnostics),
                "message": f"Channel3 returned no usable products matching the filters. Target currency: {target_currency}. Check diagnostics to see whether products were removed by currency, price, or other filters.",
            }
        return {
            "success": True,
            "count": len(products),
            "total_matched": len(products),
            "products": products,
            "sources_searched": providers_tried,
            "search_query": search_query,
            "data_source": "Channel3",
            "target_currency": target_currency,
            "diagnostics": dict(self._last_diagnostics),
        }

    @staticmethod
    def _resolve_target_currency(query: Optional[str]) -> str:
        """Resolve budget currency from explicit query wording or environment.

        FLOWPAY_SHOPPING_CURRENCY defaults to USD because the current Channel3
        workspace is configured for the US market. Set it to INR for India-market
        budget filtering. An explicit currency in the user's query takes priority.
        """
        text = (query or "").casefold()
        if "₹" in text or re.search(r"\binr\b|\brupees?\b", text):
            return "INR"
        if "$" in text or re.search(r"\busd\b|\bdollars?\b", text):
            return "USD"
        configured = os.getenv("FLOWPAY_SHOPPING_CURRENCY", "USD").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", configured):
            logger.warning(
                "Invalid FLOWPAY_SHOPPING_CURRENCY=%r; defaulting to USD", configured
            )
            return "USD"
        return configured

    @staticmethod
    def _validate_inputs(max_price: Optional[float], limit: int) -> Optional[str]:
        if isinstance(max_price, bool) or (
            max_price is not None
            and (not isinstance(max_price, (int, float)) or max_price < 0)
        ):
            return "max_price must be a non-negative number."
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return "limit must be a positive integer."
        return None

    @staticmethod
    def _build_query(
        query: Optional[str],
        features: Optional[list[str]],
        max_price: Optional[float],
        category: Optional[str],
    ) -> str:
        """Build a discovery query; budget and detailed specs are evaluated afterward.

        Channel3 should discover candidates from a concise query. Repeating every
        feature and the budget in the search string can overconstrain discovery.
        """
        base = (query or "").strip()
        cat = (category or "").strip()
        if not base:
            base = cat
        elif cat and cat.casefold() not in base.casefold():
            # Add category only when it contributes a genuinely different term.
            base_words = {
                word.rstrip("s") for word in re.findall(r"[a-z0-9]+", base.casefold())
            }
            cat_words = {
                word.rstrip("s") for word in re.findall(r"[a-z0-9]+", cat.casefold())
            }
            if cat_words and not cat_words.issubset(base_words):
                base = f"{base} {cat}"

        clean_features = []
        for feature in features or []:
            if not isinstance(feature, str) or not feature.strip():
                continue
            value = re.sub(r"\s+", " ", feature).strip()
            if value.casefold() not in {x.casefold() for x in clean_features}:
                clean_features.append(value)

        # Add only the most distinctive feature to discovery; keep all requested
        # features for evidence scoring after results are retrieved.
        if clean_features:
            distinctive = clean_features[0]
            if distinctive.casefold() not in base.casefold():
                base = f"{base} {distinctive}".strip()
        return re.sub(r"\s+", " ", base).strip()

    def _search_channel3(
        self,
        *,
        search_query: str,
        category: Optional[str],
        max_price: Optional[float],
        target_currency: str,
        requested_sources: set[str],
        requested_features: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Call the installed Channel3 SDK and normalize its Product objects."""
        from channel3_sdk import Channel3

        client = Channel3(api_key=self.channel3_api_key)
        logger.info(
            "[Channel3] Search query=%r limit=%s budget=%r target_currency=%s",
            search_query,
            limit,
            max_price,
            target_currency,
        )
        response = client.products.search(query=search_query, limit=limit)
        items = self._get(response, "items")
        if items is None:
            nested = self._get(response, "response")
            items = self._get(nested, "products") if nested is not None else None
        if items is None:
            # Some SDK/API response shapes wrap the result under data/products.
            data = self._get(response, "data")
            items = self._get(data, "products") if data is not None else None
        if not isinstance(items, (list, tuple)):
            logger.error(
                "[Channel3] Unexpected response type=%s; keys=%s",
                type(response).__name__,
                list(response.keys()) if isinstance(response, dict) else None,
            )
            raise TypeError("Channel3 response did not contain a product items list")

        logger.info("[Channel3] Raw products returned=%d", len(items))
        normalized: list[dict[str, Any]] = []
        rejected_invalid = 0
        rejected_currency = 0
        rejected_price = 0
        rejected_source = 0
        for item in items:
            product = self._normalize_channel3_product(item, category=category)
            if not product:
                rejected_invalid += 1
                logger.debug(
                    "[Channel3] Product rejected during normalization; item_type=%s",
                    type(item).__name__,
                )
                continue
            # Compare a budget only with offers in the selected currency. Never
            # compare amounts across currencies or relabel a foreign price.
            if max_price is not None:
                if (product.get("currency") or "").upper() != target_currency:
                    rejected_currency += 1
                    continue
                if product["price"] is None:
                    rejected_price += 1
                    continue
                if product["price"] > float(max_price):
                    rejected_price += 1
                    continue
            if requested_sources and not any(
                source in str(product.get("source", "")).casefold()
                for source in requested_sources
            ):
                rejected_source += 1
                continue
            product.update(self._assess_listing_evidence(product, requested_features))
            normalized.append(product)

        logger.info(
            "[Channel3] Diagnostics raw=%d normalized=%d kept=%d rejected_invalid=%d rejected_currency=%d rejected_price_or_missing=%d rejected_source=%d target_currency=%s",
            len(items),
            len(items) - rejected_invalid,
            len(normalized),
            rejected_invalid,
            rejected_currency,
            rejected_price,
            rejected_source,
            target_currency,
        )
        self._last_diagnostics = {
            "raw_count": len(items),
            "normalized_count": len(items) - rejected_invalid,
            "kept_count": len(normalized),
            "rejected_invalid": rejected_invalid,
            "rejected_currency": rejected_currency,
            "rejected_price_or_missing": rejected_price,
            "rejected_source": rejected_source,
            "target_currency": target_currency,
        }

        # Apply deterministic product decisions and rank by decision quality.
        # The engine evaluates listing evidence and hard constraints;
        # it does not independently verify the merchant or authorize purchases.
        decision_requirements = self._canonicalize_requirements(requested_features)

        ranked_products = rank_products(
            normalized,
            requirements=decision_requirements,
            max_price=max_price,
            target_currency=target_currency if max_price is not None else None,
        )

        logger.info(
            "[Channel3] Decision ranking complete: %s",
            {
                status: sum(
                    product.get("decision_status") == status
                    for product in ranked_products
                )
                for status in (
                    "qualified",
                    "partial_match",
                    "rejected",
                    "insufficient_data",
                )
            },
        )

        return ranked_products[:limit]

    @staticmethod
    def _canonicalize_requirements(requirements: list[str]) -> list[str]:
        """Normalize generic requirements and remove exact duplicates/alternatives."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in requirements:
            if not isinstance(raw, str) or not raw.strip():
                continue
            value = re.sub(r"\s+", " ", raw).strip()
            # Normalize punctuation/spacing, but preserve meaningful numbers,
            # model identifiers, units, brands, and category-specific vocabulary.
            key = re.sub(r"[^a-z0-9]+", "", value.casefold())
            if key and key not in seen:
                seen.add(key)
                cleaned.append(value)
        # Combine explicit A-or-B alternatives into one scoring criterion when the
        # model supplies both alternatives separately and the user's phrasing signals
        # they are interchangeable. This avoids favoring products for duplicate counts.
        folded = {x.casefold() for x in cleaned}
        alternatives = [
            (a, b)
            for a, b in [("intel i7", "ryzen 7"), ("android", "ios")]
            if a in folded and b in folded
        ]
        for a, b in alternatives:
            cleaned = [x for x in cleaned if x.casefold() not in {a, b}]
            cleaned.append(f"{a.title()} or {b.title()}")
        return cleaned

    @staticmethod
    def _matches_battery_requirement(requirement: str, evidence: str) -> bool:
        """
        Check whether provider listing text supports a minimum battery-life
        requirement.

        Examples:
            Requirement: minimum 30 hours battery life
            Evidence: Up to 37 hours of battery life
            Result: True

        This is a targeted text-and-number matcher, not independent
        verification of the manufacturer's claim.
        """
        requirement = requirement.casefold()
        evidence = evidence.casefold()

        # Extract the minimum requested duration from phrases such as:
        # "minimum 30 hours battery life"
        # "at least 30 hours of battery life"
        # "30+ hours battery life"
        requirement_pattern = (
            r"(?:(?:minimum|min\.?|at\s+least)\s*)?"
            r"(\d+(?:\.\d+)?)\s*\+?\s*hours?"
            r".{0,50}\bbattery\b"
        )

        requirement_match = re.search(requirement_pattern, requirement)
        if not requirement_match:
            return False

        required_hours = float(requirement_match.group(1))

        # Match either:
        # "battery life: up to 37 hours"
        # "up to 37 hours of battery life"
        evidence_pattern = (
            r"\b(?:battery(?:\s+life)?|playback|listening\s+time)"
            r"\b.{0,50}?"
            r"(\d+(?:\.\d+)?)\s*\+?\s*hours?\b"
            r"|"
            r"\b(\d+(?:\.\d+)?)\s*\+?\s*hours?\b"
            r".{0,50}?"
            r"\b(?:battery(?:\s+life)?|playback|listening\s+time)\b"
        )

        for match in re.finditer(evidence_pattern, evidence):
            hours = next(
                (float(value) for value in match.groups() if value is not None),
                None,
            )
            if hours is not None and hours >= required_hours:
                return True

        return False

    @staticmethod
    def _assess_listing_evidence(
        product: dict[str, Any], requirements: list[str]
    ) -> dict[str, Any]:
        """Compare any requested product attributes against provider-returned listing text.

        This is generic text evidence matching, not independent merchant verification.
        Missing data stays unverified; it is never treated as a match.
        """
        requirements = ExternalProductSearch._canonicalize_requirements(requirements)
        features = product.get("features") or []
        if isinstance(features, str):
            features = [features]
        evidence = " ".join(
            [str(product.get("name") or "")] + [str(x) for x in features]
        ).casefold()
        evidence = re.sub(r"\s+", " ", evidence)
        evidence_compact = re.sub(r"[^a-z0-9]+", "", evidence)
        checks = []
        for requirement in requirements:
            req = requirement.strip()
            if not req:
                continue
            alternatives = [
                part.strip()
                for part in re.split(r"\s+or\s+|\s*/\s*", req, flags=re.I)
                if part.strip()
            ]
            matched = False
            for alternative in alternatives:
                compact = re.sub(r"[^a-z0-9]+", "", alternative.casefold())
                if not compact:
                    continue
                # Conservative generic matching: normalized phrase/identifier must
                # appear in the title or provider-supplied feature/description text.
                if (
                    alternative.casefold() in evidence
                    or compact in evidence_compact
                    or ExternalProductSearch._matches_battery_requirement(
                        alternative,
                        evidence,
                    )
                ):
                    matched = True
                    break
            checks.append(
                {
                    "requirement": req,
                    "status": "supported_by_listing" if matched else "unverified",
                }
            )

        matched_count = sum(item["status"] == "supported_by_listing" for item in checks)
        unverified_count = len(checks) - matched_count
        if not checks:
            status = "not_assessed"
            summary = (
                "No structured feature requirements were supplied to the search tool."
            )
        elif unverified_count == 0:
            status = "all_requested_features_found"
            summary = "All requested attributes were found in the provider's listing text; this is not independent merchant verification."
        elif matched_count:
            status = "partial_evidence"
            summary = "Some requested attributes appear in the provider's listing text; the rest are unverified."
        else:
            status = "insufficient_evidence"
            summary = "The provider's listing text does not establish the requested attributes."
        return {
            "requirement_checks": checks,
            "matched_requirements": [
                x["requirement"]
                for x in checks
                if x["status"] == "supported_by_listing"
            ],
            "unverified_requirements": [
                x["requirement"] for x in checks if x["status"] == "unverified"
            ],
            "matched_requirement_count": matched_count,
            "unverified_requirement_count": unverified_count,
            "listing_evidence_status": status,
            "listing_evidence_summary": summary,
        }

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _normalize_channel3_product(
        self, item: Any, *, category: Optional[str]
    ) -> Optional[dict[str, Any]]:
        title = str(self._get(item, "title", "") or "").strip()
        product_id = str(self._get(item, "id", "") or "").strip()
        if not title or not product_id:
            return None

        offers = self._get(item, "offers", []) or []
        if not isinstance(offers, (list, tuple)):
            offers = []
        # Prefer an offer with a usable HTTPS URL and valid price. Do not use an
        # image URL or invent a merchant product page when no offer is available.
        selected_offer = None
        for offer in offers:
            url = self._get(offer, "url", "")
            parsed = urlparse(url if isinstance(url, str) else "")
            price_obj = self._get(offer, "price")
            amount = self._get(price_obj, "price")
            currency = str(self._get(price_obj, "currency", "") or "").upper()
            if (
                parsed.scheme == "https"
                and parsed.netloc
                and currency
                and self._valid_number(amount)
            ):
                selected_offer = offer
                break
        if selected_offer is None and offers:
            selected_offer = offers[0]

        price_obj = (
            self._get(selected_offer, "price") if selected_offer is not None else None
        )
        price_value = self._get(price_obj, "price") if price_obj is not None else None
        currency = str(self._get(price_obj, "currency", "") or "").upper() or None
        price = float(price_value) if self._valid_number(price_value) else None
        offer_url = (
            self._get(selected_offer, "url", "") if selected_offer is not None else ""
        )
        parsed_url = urlparse(offer_url if isinstance(offer_url, str) else "")
        product_url = (
            offer_url if parsed_url.scheme == "https" and parsed_url.netloc else ""
        )
        merchant = (
            str(self._get(selected_offer, "domain", "") or "Unknown retailer")
            if selected_offer
            else "Unknown retailer"
        )

        features = self._get(item, "key_features", []) or []
        if not isinstance(features, (list, tuple)):
            features = []
        features_out = [str(value).strip() for value in features if str(value).strip()]
        description = self._get(item, "description")
        if isinstance(description, str) and description.strip():
            features_out.insert(0, description.strip())

        brands = self._get(item, "brands", []) or []
        brand_names = [
            str(self._get(brand, "name", "")).strip()
            for brand in brands
            if str(self._get(brand, "name", "")).strip()
        ]
        if brand_names:
            features_out.append("Brand: " + ", ".join(brand_names))

        category_obj = self._get(item, "category")
        category_name = self._get(category_obj, "title", "") if category_obj else ""
        rating_obj = self._get(item, "ratings")
        rating_value = self._get(rating_obj, "value") if rating_obj else None
        review_count = self._get(rating_obj, "count") if rating_obj else None
        thumbnail = None
        images = self._get(item, "images", []) or []
        for image in images:
            if self._get(image, "is_main_image", False):
                thumbnail = self._get(image, "cleaned_url") or self._get(image, "url")
                if thumbnail:
                    break

        return {
            "product_id": f"channel3_{product_id}",
            "name": title,
            "price": price,
            "currency": currency,
            "features": list(dict.fromkeys(features_out)),
            "category": category_name or category or "",
            "rating": float(rating_value) if self._valid_number(rating_value) else None,
            "reviews": (
                int(review_count)
                if isinstance(review_count, int) and not isinstance(review_count, bool)
                else None
            ),
            "source": merchant,
            "url": product_url,
            "url_type": "channel3_offer" if product_url else "unavailable",
            "price_display": (
                f"{price:,.2f} {currency}"
                if price is not None and currency
                else "Price unavailable"
            ),
            "thumbnail": thumbnail,
            "data_source": "Channel3",
            "channel3_product_id": product_id,
            "availability": (
                self._get(selected_offer, "availability")
                if selected_offer is not None
                else None
            ),
            "condition": (
                self._get(selected_offer, "condition")
                if selected_offer is not None
                else None
            ),
            "offer_url_domain": parsed_url.netloc if product_url else None,
            "price_evidence_source": (
                "Channel3 offer" if price is not None else "unavailable"
            ),
            "price_independently_verified": False,
        }

    @staticmethod
    def _valid_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        )

    def get_product_by_id(self, product_id: str) -> dict[str, Any]:
        """Return a product from this process's recent search results."""
        product = self._last_results.get(str(product_id))
        if product:
            return {"success": True, "product": dict(product)}
        return {
            "success": False,
            "error": f"Product {product_id} is not in recent search results. Run a new search first.",
        }

    @staticmethod
    def _parse_price(value: Any) -> Optional[float]:
        if not isinstance(value, str):
            return None
        match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _failure(message: str, providers: Optional[list[str]] = None) -> dict[str, Any]:
        return {
            "success": False,
            "count": 0,
            "total_matched": 0,
            "products": [],
            "sources_searched": providers or [],
            "error": message,
            "data_source": "live_api",
        }

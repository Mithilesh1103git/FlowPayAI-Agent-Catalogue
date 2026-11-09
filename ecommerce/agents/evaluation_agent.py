"""Product Evaluation Agent — deterministic ranking with resilient shortlist."""

from __future__ import annotations

import re
from typing import Any

from ecommerce.product_decision_engine import rank_products

MAX_PARTIAL_ON_SHORTLIST = 8
MAX_FALLBACK_ON_SHORTLIST = 8


def _canonicalize_requirements(requirements: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in requirements or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = re.sub(r"\s+", " ", raw).strip()
        key = value.casefold()
        if key not in seen:
            cleaned.append(value)
            seen.add(key)
    return cleaned


def _evidence_text(product: dict[str, Any]) -> str:
    features = product.get("features") or []
    if isinstance(features, str):
        features = [features]
    parts = [str(product.get("name") or "")]
    parts.extend(str(x) for x in features)
    for key in ("supported_requirements", "unverified_requirements"):
        vals = product.get(key) or []
        if isinstance(vals, list):
            parts.extend(str(x) for x in vals)
    text = " ".join(parts).casefold()
    return re.sub(r"\s+", " ", text)


def _matches_storage_requirement(requirement: str, evidence: str) -> bool:
    req = requirement.casefold()
    if not re.search(r"\b(ssd|storage|disk|drive|tb|gb)\b", req):
        return False

    required_gb = None
    m_tb = re.search(r"(\d+(?:\.\d+)?)\s*tb", req)
    m_gb = re.search(r"(\d+(?:\.\d+)?)\s*gb", req)
    if m_tb:
        required_gb = float(m_tb.group(1)) * 1024
    elif m_gb:
        required_gb = float(m_gb.group(1))

    if required_gb is None:
        return bool(re.search(r"\b1\s*tb\b|\b1024\s*gb\b", evidence))

    found = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*tb", evidence):
        found.append(float(m.group(1)) * 1024)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*gb", evidence):
        found.append(float(m.group(1)))

    if not found:
        return False
    return max(found) + 1e-6 >= required_gb


def _requirement_supported(requirement: str, evidence: str) -> bool:
    req = requirement.strip()
    if not req:
        return False

    if _matches_storage_requirement(req, evidence):
        return True

    alternatives = [
        part.strip()
        for part in re.split(r"\s+or\s+|\s*/\s*", req, flags=re.I)
        if part.strip()
    ]
    evidence_compact = re.sub(r"[^a-z0-9]+", "", evidence)

    for alternative in alternatives:
        alt_cf = alternative.casefold()
        compact = re.sub(r"[^a-z0-9]+", "", alt_cf)
        if not compact:
            continue
        if alt_cf in evidence or compact in evidence_compact:
            return True
        if "rtx 4060" in alt_cf and re.search(r"rtx\s*4060", evidence):
            return True
        if "rtx 4050" in alt_cf and re.search(r"rtx\s*4050", evidence):
            return True
        if re.search(r"(\d+)\s*gb\s*ram|ram\s*(\d+)\s*gb|(\d+)\s*gb", alt_cf):
            m = re.search(r"(\d+)\s*gb", alt_cf)
            if m and re.search(rf"{m.group(1)}\s*gb", evidence):
                return True
        if re.search(r"144\s*hz", alt_cf) and re.search(r"144\s*hz", evidence):
            return True
        if "wireless" in alt_cf and re.search(r"wireless|bluetooth", evidence):
            return True
        if re.search(r"\banc\b|noise\s*cancell", alt_cf) and re.search(
            r"\banc\b|noise\s*cancell", evidence
        ):
            return True
    return False


def _refresh_listing_evidence(
    product: dict[str, Any],
    requirements: list[str],
) -> dict[str, Any]:
    requirements = _canonicalize_requirements(requirements)
    evidence = _evidence_text(product)
    checks = []
    for requirement in requirements:
        supported = _requirement_supported(requirement, evidence)
        checks.append(
            {
                "requirement": requirement,
                "status": "supported_by_listing" if supported else "unverified",
            }
        )

    matched = [
        c["requirement"] for c in checks if c["status"] == "supported_by_listing"
    ]
    unverified = [c["requirement"] for c in checks if c["status"] == "unverified"]

    updated = dict(product)
    updated["requirement_checks"] = checks
    updated["matched_requirements"] = matched
    updated["supported_requirements"] = matched
    updated["unverified_requirements"] = unverified
    updated["matched_requirement_count"] = len(matched)
    updated["unverified_requirement_count"] = len(unverified)
    if not checks:
        updated["listing_evidence_status"] = "not_assessed"
        updated["listing_evidence_summary"] = "No requirements supplied."
    elif not unverified:
        updated["listing_evidence_status"] = "all_requested_features_found"
        updated["listing_evidence_summary"] = (
            "All current requirements found in listing text."
        )
    elif matched:
        updated["listing_evidence_status"] = "partial_evidence"
        updated["listing_evidence_summary"] = (
            "Some current requirements found in listing text."
        )
    else:
        updated["listing_evidence_status"] = "insufficient_evidence"
        updated["listing_evidence_summary"] = (
            "Listing text does not support the current requirements."
        )
    return updated


def evaluation_agent(state: dict) -> dict:
    print("\n========== PRODUCT EVALUATION AGENT ==========")

    products = state.get("products", []) or []
    shopping_plan = state.get("shopping_plan", {}) or {}

    if not products:
        return {
            "evaluations": [],
            "qualified_products": [],
            "shortlisted_products": [],
            "status": "evaluation_failed",
            "errors": ["No products available for evaluation."],
        }

    requirements = shopping_plan.get("must_have", []) or []
    budget = shopping_plan.get("budget", {}) or {}
    max_price = budget.get("amount")
    # Only enforce currency when planner explicitly set one
    target_currency = budget.get("currency")
    if isinstance(target_currency, str):
        target_currency = target_currency.strip().upper() or None
    else:
        target_currency = None

    print(f"Products received: {len(products)}")
    print(f"Requirements: {requirements}")
    print(f"Budget: {max_price} {target_currency}")

    refreshed = [
        _refresh_listing_evidence(p, requirements)
        for p in products
        if isinstance(p, dict)
    ]

    evaluated_products = rank_products(
        products=refreshed,
        requirements=requirements,
        max_price=max_price,
        target_currency=target_currency,
    )

    # If everything was rejected only due to currency and planner had no currency,
    # rank_products already got target_currency=None. Secondary soft pass: budget only.
    non_rejected = [
        p for p in evaluated_products if p.get("decision_status") != "rejected"
    ]
    if not non_rejected and evaluated_products and max_price is not None:
        print("Soft re-rank without currency constraint (all rejected).")
        evaluated_products = rank_products(
            products=refreshed,
            requirements=requirements,
            max_price=max_price,
            target_currency=None,
        )

    qualified_products = [
        product
        for product in evaluated_products
        if product.get("decision_status") == "qualified"
    ]
    partial_matches = [
        product
        for product in evaluated_products
        if product.get("decision_status") == "partial_match"
    ]
    rejected_products = [
        product
        for product in evaluated_products
        if product.get("decision_status") == "rejected"
    ]
    insufficient_data = [
        product
        for product in evaluated_products
        if product.get("decision_status") == "insufficient_data"
    ]

    shortlisted_products = list(qualified_products)
    if partial_matches:
        shortlisted_products.extend(partial_matches[:MAX_PARTIAL_ON_SHORTLIST])

    # Fallback: still show best available listings so the UI is never empty
    # when Channel3 returned products.
    fallback_used = False
    if not shortlisted_products:
        fallback_used = True
        pool = [
            p
            for p in evaluated_products
            if p.get("decision_status") in {"insufficient_data", "partial_match"}
        ]
        if not pool:
            pool = [
                p for p in evaluated_products if p.get("decision_status") != "rejected"
            ]
        if not pool:
            pool = list(evaluated_products)
        shortlisted_products = pool[:MAX_FALLBACK_ON_SHORTLIST]
        for p in shortlisted_products:
            p["shortlist_fallback"] = True

    print("\n========== EVALUATION SUMMARY ==========")
    print(f"Qualified: {len(qualified_products)}")
    print(f"Partial Matches: {len(partial_matches)}")
    print(f"Rejected: {len(rejected_products)}")
    print(f"Insufficient Data: {len(insufficient_data)}")
    print(f"Shortlisted: {len(shortlisted_products)} (fallback={fallback_used})")

    return {
        "products": evaluated_products,
        "evaluations": evaluated_products,
        "qualified_products": qualified_products,
        "shortlisted_products": shortlisted_products,
        "status": "evaluation_completed",
        "shortlist_fallback": fallback_used,
    }

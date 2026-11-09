from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


class AppItem(BaseModel):
    product_id: str
    name: str = Field(..., max_length=127)
    retailer: Optional[str] = None
    product_url: Optional[HttpUrl] = None
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., decimal_places=2, gt=0)
    line_total: Decimal = Field(..., decimal_places=2, gt=0)
    currency: str = Field("USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def verify_line_total(self):
        expected = self.quantity * self.unit_price
        if self.line_total != expected:
            raise ValueError(
                f"Line total ({self.line_total}) does not match quantity * unit_price ({expected})"
            )
        return self


class AppAmount(BaseModel):
    value: Decimal = Field(..., decimal_places=2, gt=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    minor_units: Optional[int] = None


class AppOrderInput(BaseModel):
    schema_version: str
    checkout_intent_id: str
    cart_id: str
    status: str
    currency: str
    amount: AppAmount
    items: List[AppItem] = Field(..., min_length=1)
    item_count: int
    total_quantity: int
    source: Dict[str, Any]
    approval: Dict[str, Any]
    policy: Dict[str, Any]
    notes: Optional[List[str]] = None

    @model_validator(mode="after")
    def verify_grand_total(self):
        items_sum = sum(item.line_total for item in self.items)
        if self.amount.value != items_sum:
            raise ValueError(
                f"Order amount ({self.amount.value}) does not match sum of items ({items_sum})"
            )
        return self

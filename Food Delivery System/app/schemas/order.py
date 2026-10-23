
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime


class OrderCreate(BaseModel):
    address_id: int
    payment_method: Literal["COD", "Online"] = "COD"
    tip_amount: float = Field(default=0, ge=0)
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at(cls, value):
        if value is not None and value <= datetime.now():
            raise ValueError("Scheduled order time must be in the future")
        return value


class OrderStatusUpdate(BaseModel):
    status: Literal[
        "Accepted",
        "Preparing",
        "Ready for Pickup",
        "Out for Delivery",
        "Delivered",
        "Rejected",
        "Cancelled",
    ]
    rejection_reason: str | None = None


class OrderResponse(BaseModel):
    id: int
    order_number: str
    customer_id: int
    restaurant_id: int
    address_id: int
    item_total: float
    coupon_code: str | None = None
    discount_amount: float
    packaging_charges: float
    delivery_fee: float
    platform_fee: float
    gst_amount: float
    tip_amount: float
    grand_total: float
    payment_method: str
    payment_status: str
    status: str
    delivery_otp: str


class ReorderResponse(BaseModel):
    message: str
    order_id: int
    added_items: int
    skipped_items: int

from pydantic import BaseModel, Field


class OrderRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RestaurantOrderResponse(BaseModel):
    message: str
    order_id: int
    order_number: str
    status: str
    rejection_reason: str | None = None

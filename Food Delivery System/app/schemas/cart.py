from pydantic import BaseModel, Field


class CartItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1, le=10)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=10)


class CartItemResponse(BaseModel):
    id: int
    menu_item_id: int
    name: str
    quantity: int
    price: float
    line_total: float


class CartResponse(BaseModel):
    id: int
    restaurant_id: int | None
    items: list[CartItemResponse]
    item_total: float
    applied_coupon: str | None = None
    discount: float = 0.0
    item_total_after_discount: float

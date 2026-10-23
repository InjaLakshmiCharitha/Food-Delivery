from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    description: str | None = None
    discount_type: Literal["Percentage", "Flat"]
    discount_value: float = Field(gt=0)
    max_discount: float | None = Field(default=None, gt=0)
    min_order_value: float = Field(default=0, ge=0)
    restaurant_id: int | None = None
    valid_from: datetime
    valid_to: datetime
    total_usage_limit: int | None = Field(default=None, gt=0)
    per_user_limit: int = Field(default=1, gt=0)
    first_order_only: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(
        cls, value: float, info
    ) -> float:
        if (
            info.data.get("discount_type") == "Percentage"
            and value > 100
        ):
            raise ValueError(
                "Percentage discount must be between 1 and 100"
            )
        if (
            info.data.get("discount_type") == "Percentage"
            and value < 1
        ):
            raise ValueError(
                "Percentage discount must be between 1 and 100"
            )
        return value

    @field_validator("valid_to")
    @classmethod
    def validate_validity(
        cls, value: datetime, info
    ) -> datetime:
        valid_from = info.data.get("valid_from")
        if valid_from is not None and value <= valid_from:
            raise ValueError("valid_to must be after valid_from")
        return value


class CouponUpdate(BaseModel):
    description: str | None = None
    discount_value: float | None = Field(default=None, gt=0)
    max_discount: float | None = Field(default=None, gt=0)
    min_order_value: float | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    total_usage_limit: int | None = Field(default=None, gt=0)
    per_user_limit: int | None = Field(default=None, gt=0)
    first_order_only: bool | None = None


class CouponResponse(BaseModel):
    id: int
    code: str
    description: str | None = None
    discount_type: str
    discount_value: float
    max_discount: float | None = None
    min_order_value: float
    restaurant_id: int | None = None
    valid_from: datetime
    valid_to: datetime
    total_usage_limit: int | None = None
    per_user_limit: int
    first_order_only: bool
    created_by: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ApplyCouponRequest(BaseModel):
    code: str = Field(min_length=3, max_length=50)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

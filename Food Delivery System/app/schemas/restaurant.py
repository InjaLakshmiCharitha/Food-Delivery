from datetime import time
from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    cuisine_type: str = Field(min_length=2, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    opening_time: time
    closing_time: time
    delivery_radius_km: float = Field(default=5.0, gt=0)
    min_order_value: float = Field(default=0.0, ge=0)
    avg_preparation_minutes: int = Field(default=30, gt=0)


class RestaurantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    cuisine_type: str | None = None
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    opening_time: time | None = None
    closing_time: time | None = None
    delivery_radius_km: float | None = Field(default=None, gt=0)
    min_order_value: float | None = Field(default=None, ge=0)
    avg_preparation_minutes: int | None = Field(default=None, gt=0)


class RestaurantResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    cuisine_type: str
    address: str
    latitude: float
    longitude: float
    opening_time: time
    closing_time: time
    is_temporarily_closed: bool
    delivery_radius_km: float
    min_order_value: float
    avg_preparation_minutes: int
    average_rating: float
    is_active: bool
    is_open: bool = False

    model_config = ConfigDict(from_attributes=True)


class OpenStatusUpdate(BaseModel):
    is_temporarily_closed: bool


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class CategoryResponse(BaseModel):
    id: int
    restaurant_id: int
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MenuItemCreate(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    price: float = Field(gt=0)
    is_veg: bool = True
    packaging_charge: float = Field(default=0.0, ge=0)


class MenuItemUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    price: float | None = Field(default=None, gt=0)
    is_veg: bool | None = None
    packaging_charge: float | None = Field(default=None, ge=0)


class MenuAvailabilityUpdate(BaseModel):
    is_available: bool


class MenuItemResponse(BaseModel):
    id: int
    restaurant_id: int
    category_id: int
    name: str
    description: str | None = None
    price: float
    is_veg: bool
    packaging_charge: float
    is_available: bool
    is_deleted: bool

    model_config = ConfigDict(from_attributes=True)


class MenuCategoryGroup(BaseModel):
    category_id: int
    category_name: str
    items: list[MenuItemResponse]


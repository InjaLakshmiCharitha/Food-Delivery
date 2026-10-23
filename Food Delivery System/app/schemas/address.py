
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AddressCreate(BaseModel):
    label: str = Field(default="Home", min_length=1, max_length=30)
    address_line: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    pincode: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_default: bool = False

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 6:
            raise ValueError("Pincode must contain exactly 6 digits")
        return value


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=30)
    address_line: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    pincode: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_default: bool | None = None

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str | None) -> str | None:
        if value is not None and (not value.isdigit() or len(value) != 6):
            raise ValueError("Pincode must contain exactly 6 digits")
        return value


class AddressResponse(BaseModel):
    id: int
    customer_id: int
    label: str
    address_line: str
    city: str
    pincode: str
    latitude: float
    longitude: float
    is_default: bool

    model_config = ConfigDict(from_attributes=True)

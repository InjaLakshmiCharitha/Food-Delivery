from pydantic import BaseModel, Field
from datetime import datetime

class DeliveryAvailabilityUpdate(BaseModel):
    is_online: bool


class DeliveryLocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DeliveryOTPRequest(BaseModel):
    otp: str = Field(pattern=r"^\d{4}$")

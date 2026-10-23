import re
from decimal import Decimal
from datetime import time


def validate_phone(phone: str) -> str:
    """Validate a 10-digit phone number."""
    if not re.fullmatch(r"\d{10}", phone):
        raise ValueError("Phone number must contain exactly 10 digits")
    return phone


def validate_pincode(pincode: str) -> str:
    """Validate a 6-digit pincode."""
    if not re.fullmatch(r"\d{6}", pincode):
        raise ValueError("Pincode must contain exactly 6 digits")
    return pincode


def validate_price(price: Decimal) -> Decimal:
    """Validate that a price is greater than zero."""
    if price <= 0:
        raise ValueError("Price must be greater than zero")
    return price


def validate_tip(tip: Decimal) -> Decimal:
    """Validate that a tip is not negative."""
    if tip < 0:
        raise ValueError("Tip cannot be negative")
    return tip


def validate_otp(otp: str) -> str:
    """Validate a 4-digit delivery OTP."""
    if not re.fullmatch(r"\d{4}", otp):
        raise ValueError("OTP must contain exactly 4 digits")
    return otp


def validate_opening_hours(
    opening_time: time,
    closing_time: time,
) -> None:
    """Ensure opening time is earlier than closing time."""
    if opening_time >= closing_time:
        raise ValueError("Opening time must be earlier than closing time")
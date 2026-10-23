
import pytest
from decimal import Decimal

from app.routers.orders import calculate_delivery_fee


def test_delivery_fee_within_first_3_km():
    assert calculate_delivery_fee(2) == Decimal("20.00")


def test_delivery_fee_at_3_km():
    assert calculate_delivery_fee(3) == Decimal("20.00")


def test_delivery_fee_above_3_km():
    assert calculate_delivery_fee(4) == Decimal("28.00")


def test_delivery_fee_with_surge_pricing():
    assert calculate_delivery_fee(
        2,
        Decimal("1.50"),
    ) == Decimal("30.00")


def test_delivery_fee_rejects_invalid_surge():
    with pytest.raises(ValueError):
        calculate_delivery_fee(
            2,
            Decimal("3.50"),
        )

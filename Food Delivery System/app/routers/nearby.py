
from datetime import datetime
from math import ceil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import get_db
from app.models.models import Restaurant, MenuItem, Coupon
from app.utils.location import calculate_distance_km

router = APIRouter(
    prefix="/restaurants",
    tags=["Nearby Search"],
)


@router.get("/nearby")
def get_nearby_restaurants(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    name: str | None = None,
    cuisine_type: str | None = None,
    veg_only: bool = False,
    min_rating: float | None = Query(default=None, ge=0, le=5),
    has_offers: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(
        default="distance",
        pattern="^(distance|rating|estimated_delivery_minutes)$",
    ),
    order: str = Query(
        default="asc",
        pattern="^(asc|desc)$",
    ),
    db: Session = Depends(get_db),
):
    current_datetime = datetime.now()
    current_time = current_datetime.time()

    query = db.query(Restaurant).filter(
        Restaurant.is_active.is_(True),
        Restaurant.is_temporarily_closed.is_(False),
    )

    # Filter by restaurant name.
    if name:
        query = query.filter(Restaurant.name.ilike(f"%{name}%"))

    # Filter by cuisine type.
    if cuisine_type:
        query = query.filter(
            Restaurant.cuisine_type.ilike(f"%{cuisine_type}%")
        )

    # Filter by minimum rating.
    if min_rating is not None:
        query = query.filter(
            Restaurant.average_rating >= min_rating
        )

    # Filter restaurants with at least one available vegetarian item.
    if veg_only:
        query = query.filter(
            Restaurant.menu_items.any(
                and_(
                    MenuItem.is_veg.is_(True),
                    MenuItem.is_available.is_(True),
                    MenuItem.is_deleted.is_(False),
                )
            )
        )

    # Filter restaurants with at least one currently valid coupon.
    if has_offers:
        query = query.filter(
            Restaurant.coupons.any(
                and_(
                    Coupon.is_active.is_(True),
                    Coupon.valid_from <= current_datetime,
                    Coupon.valid_to >= current_datetime,
                )
            )
        )

    restaurants = query.all()
    results = []

    for restaurant in restaurants:
        # Check whether the restaurant is currently open.
        if not (
            restaurant.opening_time
            <= current_time
            <= restaurant.closing_time
        ):
            continue

        # Calculate distance from the customer's location.
        distance = calculate_distance_km(
            latitude,
            longitude,
            restaurant.latitude,
            restaurant.longitude,
        )

        # Check the restaurant's delivery radius.
        if distance > restaurant.delivery_radius_km:
            continue

        # Estimate travel time at 20 km/hour.
        travel_minutes = ceil((distance / 20) * 60)

        estimated_delivery_minutes = (
            restaurant.avg_preparation_minutes + travel_minutes
        )

        results.append({
            "id": restaurant.id,
            "name": restaurant.name,
            "cuisine_type": restaurant.cuisine_type,
            "address": restaurant.address,
            "latitude": restaurant.latitude,
            "longitude": restaurant.longitude,
            "opening_time": restaurant.opening_time,
            "closing_time": restaurant.closing_time,
            "is_open": True,
            "distance_km": distance,
            "delivery_radius_km": restaurant.delivery_radius_km,
            "avg_preparation_minutes": restaurant.avg_preparation_minutes,
            "estimated_delivery_minutes": estimated_delivery_minutes,
            "average_rating": restaurant.average_rating,
        })

    # Sort by the selected field.
    sort_fields = {
        "distance": "distance_km",
        "rating": "average_rating",
        "estimated_delivery_minutes": "estimated_delivery_minutes",
    }

    field = sort_fields[sort_by]

    results.sort(
        key=lambda restaurant: (
            restaurant[field] is None,
            restaurant[field] if restaurant[field] is not None else 0,
        ),
        reverse=(order == "desc"),
    )

    # Calculate total before pagination.
    total = len(results)

    # Apply skip and limit after filtering and sorting.
    paginated_results = results[skip:skip + limit]

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": paginated_results,
    }


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import User, Order, Restaurant, Rating
from app.utils.dependencies import get_current_customer, get_current_user


router = APIRouter(tags=["Ratings and Reviews"])


@router.post("/orders/{order_id}/rating", status_code=201)
def rate_order(
    order_id: int,
    restaurant_rating: int = Query(..., ge=1, le=5),
    partner_rating: int | None = Query(default=None, ge=1, le=5),
    comment: str | None = Query(default=None, max_length=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_customer),
):
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.customer_id == user.id,
    ).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    if order.status != "Delivered":
        raise HTTPException(
            status_code=409,
            detail="Only delivered orders can be rated",
        )

    existing_rating = db.query(Rating).filter(
        Rating.order_id == order.id
    ).first()

    if existing_rating:
        raise HTTPException(
            status_code=409,
            detail="This order has already been rated",
        )

    try:
        rating = Rating(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            customer_id=user.id,
            restaurant_rating=restaurant_rating,
            partner_rating=partner_rating,
            comment=comment,
        )

        db.add(rating)
        db.flush()

        average_rating = db.query(
            func.avg(Rating.restaurant_rating)
        ).filter(
            Rating.restaurant_id == order.restaurant_id
        ).scalar()

        restaurant = db.query(Restaurant).filter(
            Restaurant.id == order.restaurant_id
        ).first()

        if restaurant:
            restaurant.average_rating = round(
                float(average_rating or 0), 2
            )

        db.commit()
        db.refresh(rating)

        return {
            "message": "Rating submitted successfully",
            "rating_id": rating.id,
            "order_id": rating.order_id,
            "restaurant_rating": rating.restaurant_rating,
            "partner_rating": rating.partner_rating,
            "comment": rating.comment,
            "restaurant_average_rating": (
                restaurant.average_rating if restaurant else 0
            ),
        }

    except Exception:
        db.rollback()
        raise



@router.get("/restaurants/{restaurant_id}/ratings")
def get_restaurant_ratings(
    restaurant_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    # Check that the restaurant exists.
    restaurant = (
        db.query(Restaurant)
        .filter(Restaurant.id == restaurant_id)
        .first()
    )

    if not restaurant:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found",
        )

    query = db.query(Rating).filter(
        Rating.restaurant_id == restaurant_id
    )

    total = query.count()

    ratings = (
        query.order_by(Rating.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": ratings,
    }


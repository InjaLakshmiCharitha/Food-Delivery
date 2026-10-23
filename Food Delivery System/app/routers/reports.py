
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    User,
    Restaurant,
    Order,
    OrderItem,
    MenuItem,
    Coupon,
    CouponUsage,
    DeliveryPartner,
)
from app.utils.dependencies import get_current_user


router = APIRouter(
    prefix="/reports",
    tags=["Reports & Dashboards"],
)


def require_role(user: User, allowed_roles: list[str]):
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this report",
        )


def date_range(
    from_date: date | None,
    to_date: date | None,
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="from_date must be before or equal to to_date",
        )

    start = datetime.combine(
        from_date or date.min, time.min
    )
    end_exclusive = datetime.combine(
        to_date + timedelta(days=1) if to_date else date.max,
        time.min,
    )

    return start, end_exclusive


# 1. Admin dashboard: today's statistics
@router.get("/admin-dashboard")
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Admin"])

    today = date.today()
    start = datetime.combine(today, time.min)
    end = start + timedelta(days=1)

    todays_orders = db.query(Order).filter(
        Order.placed_at >= start,
        Order.placed_at < end,
    )

    total_orders = todays_orders.count()

    delivered_orders = todays_orders.filter(
        Order.status == "Delivered"
    ).count()

    cancelled_orders = todays_orders.filter(
        Order.status == "Cancelled"
    ).count()

    rejected_orders = todays_orders.filter(
        Order.status == "Rejected"
    ).count()

    revenue = (
        db.query(func.coalesce(func.sum(Order.grand_total), 0))
        .filter(
            Order.placed_at >= start,
            Order.placed_at < end,
            Order.status == "Delivered",
            Order.payment_status == "Paid",
        )
        .scalar()
    )

    discount_total = (
        db.query(func.coalesce(func.sum(Order.discount_amount), 0))
        .filter(
            Order.placed_at >= start,
            Order.placed_at < end,
        )
        .scalar()
    )

    online_partners = db.query(DeliveryPartner).filter(
        DeliveryPartner.is_online.is_(True),
        DeliveryPartner.is_approved.is_(True),
    ).count()

    delivered_records = todays_orders.filter(
        Order.status == "Delivered",
        Order.delivered_at.isnot(None),
        Order.placed_at.isnot(None),
    ).all()

    durations = [
        (order.delivered_at - order.placed_at).total_seconds() / 60
        for order in delivered_records
        if order.delivered_at >= order.placed_at
    ]

    average_delivery_minutes = (
        round(sum(durations) / len(durations), 2)
        if durations else 0
    )

    return {
        "date": today,
        "total_orders": total_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
        "rejected_orders": rejected_orders,
        "total_revenue": float(revenue or 0),
        "total_discount_given": float(discount_total or 0),
        "online_partners": online_partners,
        "average_delivery_time_minutes": average_delivery_minutes,
    }


# 2. Top 10 restaurants by orders and revenue
@router.get("/top-restaurants")
def top_restaurants(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Admin"])

    start, end = date_range(from_date, to_date)

    rows = (
        db.query(
            Restaurant.id.label("restaurant_id"),
            Restaurant.name.label("restaurant_name"),
            func.count(Order.id).label("total_orders"),
            func.coalesce(func.sum(Order.grand_total), 0).label("revenue"),
        )
        .join(Order, Order.restaurant_id == Restaurant.id)
        .filter(
            Order.placed_at >= start,
            Order.placed_at < end,
            Order.status == "Delivered",
            Order.payment_status == "Paid",
        )
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(
            func.count(Order.id).desc(),
            func.sum(Order.grand_total).desc(),
        )
        .limit(10)
        .all()
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "items": [
            {
                "restaurant_id": row.restaurant_id,
                "restaurant_name": row.restaurant_name,
                "total_orders": row.total_orders,
                "revenue": float(row.revenue or 0),
            }
            for row in rows
        ],
    }


# 3. Coupon usage report
@router.get("/coupon-usage")
def coupon_usage_report(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(
        current_user,
        ["Admin", "Restaurant Owner"],
    )

    start, end = date_range(from_date, to_date)

    query = (
        db.query(
            Coupon.id.label("coupon_id"),
            Coupon.code.label("coupon_code"),
            Coupon.restaurant_id.label("restaurant_id"),
            func.count(CouponUsage.id).label("times_used"),
            func.coalesce(
                func.sum(CouponUsage.discount_amount), 0
            ).label("total_discount"),
            func.coalesce(
                func.sum(Order.grand_total), 0
            ).label("revenue"),
        )
        .outerjoin(
            CouponUsage,
            (CouponUsage.coupon_id == Coupon.id)
            & (CouponUsage.is_released.is_(False)),
        )
        .outerjoin(Order, Order.id == CouponUsage.order_id)
        .filter(
            (Order.id.is_(None))
            | (
                (Order.placed_at >= start)
                & (Order.placed_at < end)
                & (Order.status == "Delivered")
                & (Order.payment_status == "Paid")
            )
        )
    )

    if current_user.role == "Restaurant Owner":
        owned_restaurants = db.query(Restaurant.id).filter(
            Restaurant.owner_id == current_user.id
        )
        query = query.filter(
            Coupon.restaurant_id.in_(owned_restaurants)
        )

    rows = (
        query.group_by(
            Coupon.id,
            Coupon.code,
            Coupon.restaurant_id,
        )
        .order_by(Coupon.id.desc())
        .all()
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "items": [
            {
                "coupon_id": row.coupon_id,
                "coupon_code": row.coupon_code,
                "restaurant_id": row.restaurant_id,
                "times_used": row.times_used,
                "total_discount_given": float(row.total_discount or 0),
                "revenue": float(row.revenue or 0),
            }
            for row in rows
        ],
    }


# 4. Restaurant owner's sales report
@router.get("/restaurant-sales")
def restaurant_sales(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Restaurant Owner"])

    start, end = date_range(from_date, to_date)

    restaurants = db.query(Restaurant).filter(
        Restaurant.owner_id == current_user.id
    ).all()

    if not restaurants:
        return {
            "from_date": from_date,
            "to_date": to_date,
            "daily_sales": [],
            "total_orders": 0,
            "best_selling_items": [],
            "average_preparation_time_minutes": 0,
        }

    restaurant_ids = [restaurant.id for restaurant in restaurants]

    orders = db.query(Order).filter(
        Order.restaurant_id.in_(restaurant_ids),
        Order.placed_at >= start,
        Order.placed_at < end,
    ).all()

    daily = {}

    for order in orders:
        day = order.placed_at.date().isoformat()
        if day not in daily:
            daily[day] = {
                "date": day,
                "total_orders": 0,
                "sales": 0.0,
            }

        daily[day]["total_orders"] += 1

        if (
            order.status == "Delivered"
            and order.payment_status == "Paid"
        ):
            daily[day]["sales"] += float(order.grand_total or 0)

    delivered_orders = [
        order for order in orders
        if order.status == "Delivered"
    ]

    preparation_times = [
        order.estimated_preparation_minutes
        for order in delivered_orders
        if order.estimated_preparation_minutes is not None
    ]

    # Aggregate item quantities from the owner's orders.
    order_ids = [order.id for order in orders]

    best_selling = []

    if order_ids:
        item_rows = (
            db.query(
                MenuItem.id.label("menu_item_id"),
                MenuItem.name.label("item_name"),
                func.sum(OrderItem.quantity).label("quantity_sold"),
            )
            .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
            .filter(
                OrderItem.order_id.in_(order_ids),
                MenuItem.restaurant_id.in_(restaurant_ids),
            )
            .group_by(MenuItem.id, MenuItem.name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(10)
            .all()
        )

        best_selling = [
            {
                "menu_item_id": row.menu_item_id,
                "item_name": row.item_name,
                "quantity_sold": int(row.quantity_sold or 0),
            }
            for row in item_rows
        ]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "daily_sales": sorted(
            daily.values(), key=lambda item: item["date"]
        ),
        "total_orders": len(orders),
        "best_selling_items": best_selling,
        "average_preparation_time_minutes": (
            round(
                sum(preparation_times) / len(preparation_times), 2
            )
            if preparation_times else 0
        ),
    }


# 5. Delivery partner summary
@router.get("/partner-summary")
def partner_summary(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Delivery Partner"])

    start, end = date_range(from_date, to_date)

    partner = (
        db.query(DeliveryPartner)
        .filter(DeliveryPartner.user_id == current_user.id)
        .first()
    )

    if not partner:
        raise HTTPException(
            status_code=404,
            detail="Delivery partner profile not found",
        )

    orders = db.query(Order).filter(
        Order.delivery_partner_id == partner.id,
        Order.status == "Delivered",
        Order.delivered_at >= start,
        Order.delivered_at < end,
    ).order_by(Order.delivered_at.asc()).all()

    daily = {}

    for order in orders:
        day = order.delivered_at.date().isoformat()
        if day not in daily:
            daily[day] = {
                "date": day,
                "deliveries_completed": 0,
                "total_distance_km": 0.0,
                "earnings": 0.0,
            }

        daily[day]["deliveries_completed"] += 1
        daily[day]["total_distance_km"] += float(
            order.distance_km or 0
        )

        # Assumption: delivery_fee represents the partner's earnings.
        daily[day]["earnings"] += float(order.delivery_fee or 0)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_deliveries_completed": len(orders),
        "total_distance_km": round(
            sum(float(order.distance_km or 0) for order in orders), 2
        ),
        "total_earnings": round(
            sum(float(order.delivery_fee or 0) for order in orders), 2
        ),
        "daily_summary": sorted(
            daily.values(), key=lambda item: item["date"]
        ),
    }

from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    User,
    Restaurant,
    Order,
    DeliveryPartner,
    DeliveryOffer,
    OrderStatusHistory,
    Notification,
)
from app.schemas.delivery import (
    DeliveryAvailabilityUpdate,
    DeliveryLocationUpdate,
    DeliveryOTPRequest,
)
from app.utils.dependencies import get_current_delivery_partner
from app.utils.location import calculate_distance_km
from app.websockets.connection_manager import manager

router = APIRouter(tags=["Delivery Partner"])

ACTIVE_STATUSES = [
    "Accepted",
    "Preparing",
    "Ready for Pickup",
    "Picked Up",
    "Out for Delivery",
]


def money(value):
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def get_partner(db: Session, user: User) -> DeliveryPartner:
    partner = (
        db.query(DeliveryPartner)
        .filter(DeliveryPartner.user_id == user.id)
        .with_for_update()
        .first()
    )

    if not partner:
        raise HTTPException(404, "Delivery partner profile not found")

    if not partner.is_approved or not user.is_approved:
        raise HTTPException(403, "Delivery partner is not approved")

    return partner


def notify_admins(db: Session, title: str, message: str):
    admins = db.query(User).filter(
        User.role == "Admin",
        User.is_active.is_(True),
    ).all()

    for admin in admins:
        # Avoid creating the same alert repeatedly.
        existing = db.query(Notification.id).filter(
            Notification.user_id == admin.id,
            Notification.title == title,
            Notification.message == message,
        ).first()

        if not existing:
            db.add(
                Notification(
                    user_id=admin.id,
                    title=title,
                    message=message,
                    is_read=False,
                )
            )


def record_status(db: Session, order: Order, new_status: str, user: User):
    old_status = order.status
    if old_status == new_status:
        return

    order.status = new_status
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=f"Delivery Partner:{user.id}",
        )
    )

    manager.broadcast_sync(
       f"order_{order.id}",
         {
            "event": "order_status_changed",
            "order_id": order.id,
            "old_status": old_status,
            "status": new_status,
            "changed_by": user.id,
         },
       )


def assign_next_partner(db: Session, order: Order):
    """Offer an order to the nearest eligible partner who has not been offered it before."""

    if order.delivery_partner_id is not None:
        return None

    if order.status not in ACTIVE_STATUSES:
        return None

    restaurant = db.query(Restaurant).filter(
        Restaurant.id == order.restaurant_id
    ).first()

    if not restaurant:
        return None

    # Only one live pending offer per order.
    pending = db.query(DeliveryOffer).filter(
        DeliveryOffer.order_id == order.id,
        DeliveryOffer.status == "Pending",
        DeliveryOffer.expires_at > datetime.utcnow(),
    ).first()

    if pending:
        return pending

    partners = (
        db.query(DeliveryPartner)
        .join(User, User.id == DeliveryPartner.user_id)
        .filter(
            DeliveryPartner.is_approved.is_(True),
            DeliveryPartner.is_online.is_(True),
            User.is_active.is_(True),
            User.is_approved.is_(True),
        )
        .all()
    )

    candidates = []
    now = datetime.utcnow()

    for partner in partners:
        if (
            partner.current_latitude is None
            or partner.current_longitude is None
            or partner.last_location_at is None
        ):
            continue

        # Require a recent location update.
        if now - partner.last_location_at > timedelta(minutes=10):
            continue

        distance = calculate_distance_km(
            restaurant.latitude,
            restaurant.longitude,
            partner.current_latitude,
            partner.current_longitude,
        )

        if distance > 5:
            continue

        # Skip any partner already offered this order, including declines
        # and expired offers.
        previous_offer = db.query(DeliveryOffer.id).filter(
            DeliveryOffer.order_id == order.id,
            DeliveryOffer.partner_id == partner.id,
        ).first()

        if previous_offer:
            continue

        # One active assignment/delivery per partner.
        active_order = db.query(Order.id).filter(
            Order.delivery_partner_id == partner.id,
            Order.status.in_(ACTIVE_STATUSES),
        ).first()

        if active_order:
            continue

        candidates.append((distance, partner))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    nearest = candidates[0][1]

    offer = DeliveryOffer(
        order_id=order.id,
        partner_id=nearest.id,
        status="Pending",
        offered_at=now,
        expires_at=now + timedelta(seconds=30),
    )

  
    db.add(offer)
    db.flush()

    delivery_distance = None
    address = order.address

    if (
        address
        and address.latitude is not None
        and address.longitude is not None
    ):
       delivery_distance = calculate_distance_km(
          restaurant.latitude,
          restaurant.longitude,
          address.latitude,
          address.longitude,
        )

    expected_earnings = (
      Decimal("25")
      + Decimal("6") * Decimal(str(delivery_distance or 0))
      + Decimal(str(order.tip_amount or 0))
    )

    manager.broadcast_sync(
      f"partner_user_{nearest.user_id}",
    {
        "event": "delivery_offer",
        "offer_id": offer.id,
        "order_id": order.id,
        "order_number": order.order_number,
        "restaurant_name": restaurant.name,
        "pickup_distance_km": candidates[0][0],
        "delivery_distance_km": delivery_distance,
        "expected_earnings": float(money(expected_earnings)),
        "seconds_remaining": 30,
        "expires_at": offer.expires_at.isoformat(),
    },
    )
    return offer


def retry_unassigned_orders(db: Session):
    """
    Called by APScheduler every minute.
    Expires old offers, tries the next partner, and notifies Admin after
    15 minutes without assignment.
    """
    now = datetime.utcnow()

    expired = db.query(DeliveryOffer).filter(
        DeliveryOffer.status == "Pending",
        DeliveryOffer.expires_at <= now,
    ).all()

    for offer in expired:
        offer.status = "Expired"

    db.flush()

    orders = db.query(Order).filter(
        Order.delivery_partner_id.is_(None),
        Order.status.in_(ACTIVE_STATUSES),
    ).all()

    for order in orders:
        if order.delivery_partner_id is not None:
            continue

        age = now - (order.placed_at or now)

        if age >= timedelta(minutes=15):
            title = f"Delivery unassigned: {order.order_number}"
            message = (
                f"Order {order.order_number} has no delivery partner "
                f"after 15 minutes."
            )
            notify_admins(db, title, message)

        assign_next_partner(db, order)

    db.commit()


def run_delivery_assignment_job():
    db = next(get_db())
    try:
        retry_unassigned_orders(db)
    finally:
        db.close()


def assign_nearest_partner(db, order):
    """
    Assign the nearest eligible delivery partner by creating an offer.
    """
    return assign_next_partner(db, order)


@router.put("/partners/me/availability")
def update_availability(
    data: DeliveryAvailabilityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        if data.is_online and (
            partner.current_latitude is None
            or partner.current_longitude is None
            or partner.last_location_at is None
        ):
            raise HTTPException(400, "Update your location before going online")

        partner.is_online = data.is_online
        db.commit()

        return {
            "message": "Availability updated",
            "is_online": partner.is_online,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not update availability")


@router.put("/partners/me/location")
def update_location(
    data: DeliveryLocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)
        partner.current_latitude = data.latitude
        partner.current_longitude = data.longitude
        partner.last_location_at = datetime.utcnow()
        db.commit()

        from app.routers.tracking import tracking_payload

        active_orders = db.query(Order).filter(
           Order.delivery_partner_id == partner.id,
           Order.status.in_(ACTIVE_STATUSES),
        ).all()

        for order in active_orders:
            manager.broadcast_sync(
               f"order_{order.id}",
               tracking_payload(db, order),
        )

        return {
            "message": "Location updated",
            "latitude": partner.current_latitude,
            "longitude": partner.current_longitude,
            "last_location_at": partner.last_location_at,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not update location")


@router.get("/partners/me/offers")
def get_my_offers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    partner = get_partner(db, user)
    now = datetime.utcnow()

    expired = db.query(DeliveryOffer).filter(
        DeliveryOffer.partner_id == partner.id,
        DeliveryOffer.status == "Pending",
        DeliveryOffer.expires_at <= now,
    ).all()

    for offer in expired:
        offer.status = "Expired"

    db.commit()

    offers = db.query(DeliveryOffer).filter(
        DeliveryOffer.partner_id == partner.id,
        DeliveryOffer.status == "Pending",
        DeliveryOffer.expires_at > now,
    ).order_by(DeliveryOffer.offered_at.desc()).all()

    return [
        {
            "offer_id": offer.id,
            "order_id": offer.order_id,
            "status": offer.status,
            "offered_at": offer.offered_at,
            "expires_at": offer.expires_at,
            "seconds_remaining": max(
                0, int((offer.expires_at - now).total_seconds())
            ),
        }
        for offer in offers
    ]


@router.put("/offers/{offer_id}/accept")
def accept_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        offer = db.query(DeliveryOffer).filter(
            DeliveryOffer.id == offer_id,
            DeliveryOffer.partner_id == partner.id,
        ).with_for_update().first()

        if not offer:
            raise HTTPException(404, "Offer not found")

        if offer.status != "Pending":
            raise HTTPException(409, "Offer is no longer pending")

        if offer.expires_at <= datetime.utcnow():
            offer.status = "Expired"
            db.commit()
            raise HTTPException(409, "Offer has expired")

        order = db.query(Order).filter(
            Order.id == offer.order_id
        ).with_for_update().first()

        if not order:
            raise HTTPException(404, "Order not found")

        if order.delivery_partner_id is not None:
            raise HTTPException(409, "Another partner already accepted this order")

        if order.status not in ACTIVE_STATUSES:
            raise HTTPException(409, "Order is not available for delivery")

        active_order = db.query(Order.id).filter(
            Order.delivery_partner_id == partner.id,
            Order.status.in_(ACTIVE_STATUSES),
        ).first()

        if active_order:
            raise HTTPException(409, "You already have an active delivery")

        offer.status = "Accepted"
        order.delivery_partner_id = partner.id

        # Expire any other pending offers for this order.
        db.query(DeliveryOffer).filter(
            DeliveryOffer.order_id == order.id,
            DeliveryOffer.id != offer.id,
            DeliveryOffer.status == "Pending",
        ).update(
            {"status": "Expired"},
            synchronize_session=False,
        )

        db.commit()

        return {
            "message": "Offer accepted",
            "order_id": order.id,
            "status": order.status,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not accept offer")


@router.put("/offers/{offer_id}/decline")
def decline_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        offer = db.query(DeliveryOffer).filter(
            DeliveryOffer.id == offer_id,
            DeliveryOffer.partner_id == partner.id,
        ).with_for_update().first()

        if not offer:
            raise HTTPException(404, "Offer not found")

        if offer.status != "Pending":
            raise HTTPException(409, "Only pending offers can be declined")

        offer.status = "Declined"
        db.flush()

        order = db.query(Order).filter(
            Order.id == offer.order_id
        ).with_for_update().first()

        next_offer = None
        if order and order.delivery_partner_id is None:
            next_offer = assign_next_partner(db, order)

        db.commit()

        return {
            "message": "Offer declined",
            "offer_id": offer.id,
            "next_offer_created": next_offer is not None,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not decline offer")


@router.put("/orders/{order_id}/pickup")
def pickup_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        order = db.query(Order).filter(
            Order.id == order_id,
            Order.delivery_partner_id == partner.id,
        ).with_for_update().first()

        if not order:
            raise HTTPException(404, "Assigned order not found")

        if order.status != "Ready for Pickup":
            raise HTTPException(409, "Order must be Ready for Pickup")

        record_status(db, order, "Picked Up", user)
        db.commit()

        return {"message": "Pickup confirmed", "status": order.status}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not confirm pickup")


@router.put("/orders/{order_id}/out-for-delivery")
def out_for_delivery(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        order = db.query(Order).filter(
            Order.id == order_id,
            Order.delivery_partner_id == partner.id,
        ).with_for_update().first()

        if not order:
            raise HTTPException(404, "Assigned order not found")

        if order.status != "Picked Up":
            raise HTTPException(409, "Order must be picked up first")

        record_status(db, order, "Out for Delivery", user)
        db.commit()

        return {"message": "Order is out for delivery", "status": order.status}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not update delivery status")


@router.put("/orders/{order_id}/deliver")
def deliver_order(
    order_id: int,
    data: DeliveryOTPRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    try:
        partner = get_partner(db, user)

        order = db.query(Order).filter(
            Order.id == order_id,
            Order.delivery_partner_id == partner.id,
        ).with_for_update().first()

        if not order:
            raise HTTPException(404, "Assigned order not found")

        if order.status != "Out for Delivery":
            raise HTTPException(409, "Order must be Out for Delivery first")

        if order.delivery_locked:
            raise HTTPException(423, "Delivery OTP verification is locked")

        if data.otp != order.delivery_otp:
            order.otp_attempts = (order.otp_attempts or 0) + 1

            if order.otp_attempts >= 3:
                order.delivery_locked = True
                notify_admins(
                    db,
                    f"Delivery OTP locked: {order.order_number}",
                    f"Order {order.order_number} was locked after three incorrect OTP attempts.",
                )

            db.commit()

            if order.delivery_locked:
                raise HTTPException(423, "Three incorrect OTP attempts; Admin notified")

            raise HTTPException(
                400,
                f"Incorrect OTP. Attempts remaining: {3 - order.otp_attempts}",
            )

        record_status(db, order, "Delivered", user)
        order.delivered_at = datetime.utcnow()

        if order.payment_method == "COD":
            order.payment_status = "Paid"

        db.commit()

        return {
            "message": "Delivery completed",
            "order_id": order.id,
            "status": order.status,
            "payment_status": order.payment_status,
            "delivered_at": order.delivered_at,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not complete delivery")


@router.get("/partners/me/earnings")
def get_earnings(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_delivery_partner),
):
    partner = get_partner(db, user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must be on or before end_date")

    query = db.query(Order).filter(
        Order.delivery_partner_id == partner.id,
        Order.status == "Delivered",
        Order.delivered_at.isnot(None),
    )

    if start_date:
        query = query.filter(
            Order.delivered_at >= datetime.combine(start_date, datetime.min.time())
        )

    if end_date:
        query = query.filter(
            Order.delivered_at < datetime.combine(
                end_date + timedelta(days=1), datetime.min.time()
            )
        )

    orders = query.order_by(Order.delivered_at.desc()).all()
    today = date.today()

    def earning(order):
        # distance_km is stored on the order during checkout.
        return money(
            Decimal("25")
            + Decimal("6") * Decimal(str(order.distance_km or 0))
            + Decimal(str(order.tip_amount or 0))
        )

    today_orders = [
        order for order in orders
        if order.delivered_at.date() == today
    ]

    return {
        "today": {
            "deliveries": len(today_orders),
            "earnings": float(sum(
                (earning(order) for order in today_orders),
                Decimal("0.00"),
            )),
        },
        "date_range": {
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
            "deliveries": len(orders),
            "earnings": float(sum(
                (earning(order) for order in orders),
                Decimal("0.00"),
            )),
        },
        "currency": "INR",
        "deliveries": [
            {
                "order_id": order.id,
                "order_number": order.order_number,
                "delivered_at": order.delivered_at,
                "distance_km": float(order.distance_km or 0),
                "tip_amount": float(order.tip_amount or 0),
                "earnings": float(earning(order)),
            }
            for order in orders
        ],
    }


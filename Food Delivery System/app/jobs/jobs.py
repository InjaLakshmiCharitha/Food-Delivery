from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.models import (
    User,
    Order,
    DeliveryOffer,
    DeliveryPartner,
    Coupon,
    Notification,
)
from app.websockets.connection_manager import manager


def create_notification(db: Session, user_id: int, title: str, message: str):
    """Create a notification for a user."""
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            is_read=False,
        )
    )


def notify_admins(db: Session, title: str, message: str):
    """Notify active administrators without creating duplicate alerts."""
    admins = db.query(User).filter(
        User.role == "Admin",
        User.is_active.is_(True),
    ).all()

    for admin in admins:
        existing = db.query(Notification.id).filter(
            Notification.user_id == admin.id,
            Notification.title == title,
            Notification.message == message,
        ).first()

        if not existing:
            create_notification(db, admin.id, title, message)


def record_system_status(
    db: Session,
    order: Order,
    new_status: str,
):
    """Update an order status and record the change as System."""
    old_status = order.status
    order.status = new_status

    from app.models.models import OrderStatusHistory

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by="System",
        )
    )

    return old_status


def auto_reject_orders():
    """Reject orders that remain Placed for more than five minutes."""
    db = SessionLocal()
    broadcasts = []

    try:
        cutoff = datetime.utcnow() - timedelta(minutes=5)

        orders = (
            db.query(Order)
            .filter(
                Order.status == "Placed",
                Order.placed_at <= cutoff,
            )
            .with_for_update()
            .all()
        )

        for order in orders:
            old_status = record_system_status(db, order, "Rejected")
            order.rejection_reason = "Restaurant did not respond"

            # Refund online payments.
            if order.payment_method == "Online":
                order.payment_status = "Refunded"

            # Release coupon usage so it does not count against limits.
            usage = order.coupon_usage
            if usage and not usage.is_released:
                usage.is_released = True

            create_notification(
                db,
                order.customer_id,
                "Order automatically rejected",
                (
                    f"Order {order.order_number} was rejected because "
                    "the restaurant did not respond within five minutes."
                ),
            )

            broadcasts.append({
                "room": f"order_{order.id}",
                "message": {
                    "event": "order_auto_rejected",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "old_status": old_status,
                    "status": "Rejected",
                    "reason": "Restaurant did not respond",
                    "changed_by": "System",
                },
            })

        db.commit()

        # Broadcast only after the transaction has committed.
        for item in broadcasts:
            manager.broadcast_sync(item["room"], item["message"])

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def expire_delivery_offers():
    """Expire offers after 30 seconds and try the next eligible partner."""
    from app.routers.delivery import assign_next_partner

    db = SessionLocal()

    try:
        now = datetime.utcnow()

        expired_offers = (
            db.query(DeliveryOffer)
            .filter(
                DeliveryOffer.status == "Pending",
                DeliveryOffer.expires_at <= now,
            )
            .with_for_update()
            .all()
        )

        affected_order_ids = set()

        for offer in expired_offers:
            offer.status = "Expired"
            affected_order_ids.add(offer.order_id)

        db.commit()

        # Retry each affected order after expiration is committed.
        for order_id in affected_order_ids:
            order = (
                db.query(Order)
                .filter(Order.id == order_id)
                .with_for_update()
                .first()
            )

            if (
                order
                and order.delivery_partner_id is None
                and order.status in [
                    "Accepted",
                    "Preparing",
                    "Ready for Pickup",
                    "Picked Up",
                    "Out for Delivery",
                ]
            ):
                assign_next_partner(db, order)
                db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def retry_unassigned_orders_job():
    """Retry unassigned delivery orders and alert Admin after 15 minutes."""
    from app.routers.delivery import retry_unassigned_orders

    db = SessionLocal()

    try:
        retry_unassigned_orders(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_inactive_partners_offline():
    """Set partners Offline if their location has not updated for 10 minutes."""
    db = SessionLocal()

    try:
        cutoff = datetime.utcnow() - timedelta(minutes=10)

        partners = db.query(DeliveryPartner).filter(
            DeliveryPartner.is_online.is_(True),
        ).all()

        for partner in partners:
            if (
                partner.last_location_at is None
                or partner.last_location_at < cutoff
            ):
                partner.is_online = False

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def deactivate_expired_coupons():
    """Deactivate coupons whose validity period has ended."""
    db = SessionLocal()

    try:
        now = datetime.utcnow()

        db.query(Coupon).filter(
            Coupon.is_active.is_(True),
            Coupon.valid_to < now,
        ).update(
            {"is_active": False},
            synchronize_session=False,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()



def process_scheduled_orders():
    """Activate scheduled orders when their scheduled time arrives."""
    db = SessionLocal()
    broadcasts = []

    try:
        now = datetime.utcnow()

        orders = (
            db.query(Order)
            .filter(
                Order.status == "Scheduled",
                Order.scheduled_at.isnot(None),
                Order.scheduled_at <= now,
            )
            .with_for_update()
            .all()
        )

        for order in orders:
            old_status = order.status

            record_system_status(db, order, "Placed")

            broadcasts.append({
                "room": f"restaurant_user_{order.restaurant.owner_id}",
                "message": {
                    "event": "new_order",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "restaurant_id": order.restaurant_id,
                    "old_status": old_status,
                    "status": "Placed",
                    "changed_by": "System",
                },
            })

            broadcasts.append({
                "room": f"order_{order.id}",
                "message": {
                    "event": "scheduled_order_activated",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "old_status": old_status,
                    "status": "Placed",
                    "changed_by": "System",
                },
            })

        db.commit()

        for item in broadcasts:
            manager.broadcast_sync(item["room"], item["message"])

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


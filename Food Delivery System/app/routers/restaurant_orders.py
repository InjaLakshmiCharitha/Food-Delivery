
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    User,
    Restaurant,
    Order,
    OrderStatusHistory,
)
from app.schemas.restaurant_order import OrderRejectRequest
from app.utils.dependencies import get_current_restaurant_owner
from app.routers.delivery import assign_nearest_partner
from app.websockets.connection_manager import manager

router = APIRouter(
    prefix="/restaurant-orders",
    tags=["Restaurant Order Handling"],
)


def get_owned_order(
    order_id: int,
    owner: User,
    db: Session,
) -> Order:
    order = (
        db.query(Order)
        .join(Restaurant, Order.restaurant_id == Restaurant.id)
        .filter(
            Order.id == order_id,
            Restaurant.owner_id == owner.id,
        )
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found for your restaurant",
        )

    return order


def change_order_status(
    db: Session,
    order: Order,
    new_status: str,
    owner: User,
):
    old_status = order.status

    order.status = new_status

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=f"Restaurant Owner:{owner.id}",
        )
    )

    manager.broadcast_sync(
        f"order_{order.id}",
        {
            "event": "order_status_changed",
            "order_id": order.id,
            "old_status": old_status,
            "status": new_status,
             "changed_by": owner.id,
        },
    )


@router.get("/restaurants/me/orders")
def get_restaurant_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    # Get only restaurants belonging to this owner.
    restaurants = (
        db.query(Restaurant.id)
        .filter(Restaurant.owner_id == owner.id)
        .subquery()
    )

    # Build the order query for the owner's restaurants.
    query = db.query(Order).filter(
        Order.restaurant_id.in_(restaurants)
    )

    # Count orders before applying pagination.
    total = query.count()

    # Apply sorting, skip, and limit.
    orders = (
        query
        .order_by(Order.placed_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "customer_id": order.customer_id,
                "status": order.status,
                "item_total": float(order.item_total),
                "grand_total": float(order.grand_total),
                "payment_method": order.payment_method,
                "payment_status": order.payment_status,
                "placed_at": order.placed_at,
                "rejection_reason": order.rejection_reason,
            }
            for order in orders
        ],
    }


@router.put("/{order_id}/accept")
def accept_order(
    order_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    try:
        order = get_owned_order(order_id, owner, db)

        if order.status != "Placed":
            raise HTTPException(
                status_code=409,
                detail="Only Placed orders can be accepted",
            )

        change_order_status(db, order, "Accepted", owner)
        db.commit()
        db.refresh(order)

        return {
            "message": "Order accepted successfully",
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to accept order",
        )


@router.put("/{order_id}/reject")
def reject_order(
    order_id: int,
    data: OrderRejectRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    try:
        order = get_owned_order(order_id, owner, db)

        if order.status != "Placed":
            raise HTTPException(
                status_code=409,
                detail="Only Placed orders can be rejected",
            )

        order.rejection_reason = data.reason.strip()

        change_order_status(db, order, "Rejected", owner)

        # Refund mock Online payments and release coupon usage.
        if order.payment_method == "Online":
            order.payment_status = "Refunded"

        if order.coupon_usage and not order.coupon_usage.is_released:
            order.coupon_usage.is_released = True

        db.commit()
        db.refresh(order)

        return {
            "message": "Order rejected successfully",
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "rejection_reason": order.rejection_reason,
            "payment_status": order.payment_status,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to reject order",
        )


@router.put("/{order_id}/preparing")
def mark_preparing(
    order_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    try:
        order = get_owned_order(order_id, owner, db)

        if order.status != "Accepted":
            raise HTTPException(
                status_code=409,
                detail="Only Accepted orders can be marked Preparing",
            )

        change_order_status(db, order, "Preparing", owner)
        db.commit()
        db.refresh(order)

        return {
            "message": "Order preparation started",
            "order_id": order.id,
            "status": order.status,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update order status",
        )


@router.put("/{order_id}/ready")
def mark_ready(
    order_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    try:
        order = get_owned_order(order_id, owner, db)

        if order.status != "Preparing":
            raise HTTPException(
                status_code=409,
                detail="Only Preparing orders can be marked Ready for Pickup",
            )

        change_order_status(db, order, "Ready for Pickup", owner)
        offer = assign_nearest_partner(db, order)
        db.commit()
        db.refresh(order)

        return {
            "message": "Order is ready for pickup",
            "order_id": order.id,
            "status": order.status,
            "delivery_offer_created": offer is not None,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update order status",
        )

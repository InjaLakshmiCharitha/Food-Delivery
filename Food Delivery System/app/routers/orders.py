from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.models import (
    User,
    Address,
    Restaurant,
    Cart,
    CartItem,
    MenuItem,
    Coupon,
    CouponUsage,
    Order,
    OrderItem,
    OrderStatusHistory,
)
from app.schemas.order import OrderCreate
from app.utils.dependencies import (
    get_current_customer,
    get_current_user,
)
from app.utils.location import calculate_distance_km
from app.websockets.connection_manager import manager

router = APIRouter(prefix="/orders", tags=["Orders"])


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def restaurant_is_open(restaurant, now):
    opening = restaurant.opening_time
    closing = restaurant.closing_time
    current = now.time()

    if opening <= closing:
        return opening <= current <= closing

    return current >= opening or current <= closing


def get_surge_multiplier(now=None):
    if now is None:
        now = datetime.now()

    current_time = now.time()

    # Peak hours: lunch and dinner
    lunch_start = time(12, 0)
    lunch_end = time(14, 0)
    dinner_start = time(19, 0)
    dinner_end = time(22, 0)

    if (
        lunch_start <= current_time < lunch_end
        or dinner_start <= current_time < dinner_end
    ):
        return Decimal("1.50")

    return Decimal("1.00")


def calculate_delivery_fee(
    distance_km,
    surge_multiplier=None,
):
    """Calculate delivery fee with surge pricing."""

    if surge_multiplier is None:
        surge_multiplier = get_surge_multiplier()

    extra_km = max(0, ceil(distance_km - 3))

    base_fee = money(
        Decimal("20") + Decimal("8") * extra_km
    )

    multiplier = Decimal(str(surge_multiplier))

    if not Decimal("1.00") <= multiplier <= Decimal("3.00"):
        raise ValueError(
            "Surge multiplier must be between 1.0 and 3.0"
        )

    return money(base_fee * multiplier)


def release_coupon_usage(db, order):
    usage = (
        db.query(CouponUsage)
        .filter(
            CouponUsage.order_id == order.id,
            CouponUsage.is_released.is_(False),
        )
        .first()
    )

    if usage:
        usage.is_released = True


def record_status(db, order, new_status, changed_by):
    old_status = order.status

    if old_status == new_status:
        return

    order.status = new_status

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
        )
    )


def order_access_check(db, order, user):
    if user.role == "Admin":
        return

    if user.role == "Customer":
        if order.customer_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )
        return

    if user.role == "Restaurant Owner":
        restaurant = db.query(Restaurant).filter(
            Restaurant.id == order.restaurant_id,
            Restaurant.owner_id == user.id,
        ).first()

        if not restaurant:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )
        return

    if user.role == "Delivery Partner":
        partner = user.delivery_partner

        if not partner or order.delivery_partner_id != partner.id:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )
        return

    raise HTTPException(
        status_code=403,
        detail="Access denied",
    )


def serialize_order(order, include_otp=False):
    result = {
        "id": order.id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "restaurant_id": order.restaurant_id,
        "address_id": order.address_id,
        "delivery_partner_id": order.delivery_partner_id,
        "item_total": float(order.item_total),
        "coupon_code": order.coupon_code,
        "discount_amount": float(order.discount_amount),
        "packaging_charges": float(order.packaging_charges),
        "delivery_fee": float(order.delivery_fee),
        "platform_fee": float(order.platform_fee),
        "gst_amount": float(order.gst_amount),
        "tip_amount": float(order.tip_amount),
        "grand_total": float(order.grand_total),
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "status": order.status,
        "distance_km": order.distance_km,
        "placed_at": order.placed_at,
        "delivered_at": order.delivered_at,
        "scheduled_at": order.scheduled_at,
    }

    if include_otp:
        result["delivery_otp"] = order.delivery_otp

    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
def place_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    try:
        now = datetime.now()

        # Validate the requested scheduled time.
        if data.scheduled_at is not None:
            if data.scheduled_at <= now:
                raise HTTPException(
                    status_code=400,
                    detail="Scheduled order time must be in the future",
                )

        cart = (
            db.query(Cart)
            .options(
                joinedload(Cart.items).joinedload(CartItem.menu_item)
            )
            .filter(Cart.customer_id == customer.id)
            .first()
        )

        if not cart or not cart.items:
            raise HTTPException(
                status_code=400,
                detail="Your cart is empty",
            )

        address = db.query(Address).filter(
            Address.id == data.address_id,
            Address.customer_id == customer.id,
        ).first()

        if not address:
            raise HTTPException(
                status_code=404,
                detail="Address not found",
            )

        restaurant = db.query(Restaurant).filter(
            Restaurant.id == cart.restaurant_id
        ).first()

        if not restaurant or not restaurant.is_active:
            raise HTTPException(
                status_code=400,
                detail="Restaurant is unavailable",
            )

        if restaurant.is_temporarily_closed:
            raise HTTPException(
                status_code=400,
                detail="Restaurant is temporarily closed",
            )

        # A scheduled order can be placed while the restaurant is
        # currently closed, but it must be open at the scheduled time.
        if data.scheduled_at is None:
            if not restaurant_is_open(restaurant, now):
                raise HTTPException(
                    status_code=400,
                    detail="Restaurant is closed",
                )
        else:
            scheduled_time = data.scheduled_at

            if not restaurant_is_open(restaurant, scheduled_time):
                raise HTTPException(
                    status_code=400,
                    detail="Restaurant is not open at the scheduled time",
                )

        distance = calculate_distance_km(
            address.latitude,
            address.longitude,
            restaurant.latitude,
            restaurant.longitude,
        )

        if distance > restaurant.delivery_radius_km:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Delivery address is outside the restaurant's "
                    "delivery radius"
                ),
            )

        item_total = Decimal("0.00")
        packaging_total = Decimal("0.00")
        snapshots = []

        for cart_item in cart.items:
            item = cart_item.menu_item

            if (
                not item
                or item.is_deleted
                or not item.is_available
                or item.restaurant_id != restaurant.id
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Cart contains an unavailable menu item",
                )

            if not 1 <= cart_item.quantity <= 10:
                raise HTTPException(
                    status_code=400,
                    detail="Each item quantity must be from 1 to 10",
                )

            price = money(item.price)
            packaging = money(item.packaging_charge)
            quantity = cart_item.quantity
            line_total = money(price * quantity)

            item_total += line_total
            packaging_total += money(packaging * quantity)

            snapshots.append({
                "menu_item_id": item.id,
                "item_name": item.name,
                "unit_price": price,
                "quantity": quantity,
                "packaging_charge": packaging,
                "line_total": line_total,
            })

        item_total = money(item_total)
        packaging_total = money(packaging_total)

        if item_total < money(restaurant.min_order_value):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Minimum order value is "
                    f"₹{restaurant.min_order_value}"
                ),
            )

        # Validate the coupon.
        coupon = None
        discount = Decimal("0.00")

        if cart.coupon_id:
            coupon = db.query(Coupon).filter(
                Coupon.id == cart.coupon_id
            ).first()

            coupon_now = datetime.utcnow()

            if (
                not coupon
                or not coupon.is_active
                or not coupon.valid_from <= coupon_now <= coupon.valid_to
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Selected coupon is no longer valid",
                )

            if coupon.restaurant_id not in (None, restaurant.id):
                raise HTTPException(
                    status_code=400,
                    detail="Coupon is not valid for this restaurant",
                )

            if item_total < money(coupon.min_order_value):
                raise HTTPException(
                    status_code=400,
                    detail="Coupon minimum order value not met",
                )

            if coupon.first_order_only and db.query(Order.id).filter(
                Order.customer_id == customer.id
            ).first():
                raise HTTPException(
                    status_code=400,
                    detail="Coupon is valid only for the first order",
                )

            usage_query = db.query(CouponUsage).filter(
                CouponUsage.coupon_id == coupon.id,
                CouponUsage.is_released.is_(False),
            )

            if (
                coupon.total_usage_limit is not None
                and usage_query.count() >= coupon.total_usage_limit
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Coupon usage limit reached",
                )

            if usage_query.filter(
                CouponUsage.customer_id == customer.id
            ).count() >= coupon.per_user_limit:
                raise HTTPException(
                    status_code=400,
                    detail="Your coupon usage limit has been reached",
                )

            value = Decimal(str(coupon.discount_value))

            if coupon.discount_type.lower() in (
                "percentage",
                "percent",
            ):
                if not Decimal("0") < value <= Decimal("100"):
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid percentage coupon",
                    )

                discount = item_total * value / Decimal("100")

                if coupon.max_discount is not None:
                    discount = min(
                        discount,
                        money(coupon.max_discount),
                    )

            elif coupon.discount_type.lower() == "flat":
                discount = value

            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported coupon type",
                )

            discount = money(min(discount, item_total))

        # Surge pricing currently defaults to normal pricing.
        # Demand-based surge detection is not configured yet.
        surge_multiplier = Decimal(now)
        delivery_fee = calculate_delivery_fee(
            distance,
            surge_multiplier,
        )

        platform_fee = Decimal("5.00")
        tip = money(data.tip_amount)
        gst = money((item_total - discount) * Decimal("0.05"))

        grand_total = money(
            item_total
            - discount
            + packaging_total
            + delivery_fee
            + platform_fee
            + gst
            + tip
        )

        # Generate a daily order number.
        today = datetime.now().strftime("%Y%m%d")

        daily_count = db.query(Order.id).filter(
            Order.order_number.like(f"ORD-{today}-%")
        ).count()

        order_number = f"ORD-{today}-{daily_count + 1:04d}"

        initial_status = (
            "Scheduled"
            if data.scheduled_at is not None
            else "Placed"
        )

        order = Order(
            order_number=order_number,
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            address_id=address.id,
            item_total=item_total,
            coupon_code=coupon.code if coupon else None,
            discount_amount=discount,
            packaging_charges=packaging_total,
            delivery_fee=delivery_fee,
            platform_fee=platform_fee,
            gst_amount=gst,
            tip_amount=tip,
            grand_total=grand_total,
            payment_method=data.payment_method,
            payment_status=(
                "Paid"
                if data.payment_method == "Online"
                else "Pending"
            ),
            status=initial_status,
            scheduled_at=data.scheduled_at,
            distance_km=distance,
            delivery_otp=f"{secrets.randbelow(10000):04d}",
            estimated_preparation_minutes=(
                restaurant.avg_preparation_minutes
            ),
        )

        db.add(order)
        db.flush()

        for snapshot in snapshots:
            db.add(
                OrderItem(
                    order_id=order.id,
                    **snapshot,
                )
            )

        db.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=None,
                new_status=initial_status,
                changed_by=f"Customer:{customer.id}",
            )
        )

        if coupon:
            db.add(
                CouponUsage(
                    coupon_id=coupon.id,
                    customer_id=customer.id,
                    order_id=order.id,
                    discount_amount=discount,
                    is_released=False,
                )
            )

        cart.items.clear()
        cart.restaurant_id = None
        cart.coupon_id = None

        db.commit()
        db.refresh(order)

        # Tell the restaurant whether this is a normal or scheduled order.
        manager.broadcast_sync(
            f"restaurant_user_{order.restaurant.owner_id}",
            {
                "event": (
                    "scheduled_order_created"
                    if order.status == "Scheduled"
                    else "new_order"
                ),
                "order_id": order.id,
                "order_number": order.order_number,
                "restaurant_id": order.restaurant_id,
                "status": order.status,
                "scheduled_at": (
                    order.scheduled_at.isoformat()
                    if order.scheduled_at
                    else None
                ),
                "grand_total": float(order.grand_total),
                "placed_at": (
                    order.placed_at.isoformat()
                    if order.placed_at
                    else None
                ),
            },
        )

        return {
            "message": (
                "Order scheduled successfully"
                if order.status == "Scheduled"
                else "Order placed successfully"
            ),
            **serialize_order(order, include_otp=True),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Order placement failed; check server logs",
        )


@router.get("/")
def get_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    restaurant_id: int | None = Query(default=None, ge=1),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Order)

    if current_user.role == "Customer":
        query = query.filter(
            Order.customer_id == current_user.id
        )

    elif current_user.role == "Restaurant Owner":
        restaurant_ids = db.query(Restaurant.id).filter(
            Restaurant.owner_id == current_user.id
        )

        query = query.filter(
            Order.restaurant_id.in_(restaurant_ids)
        )

    elif current_user.role == "Delivery Partner":
        partner = current_user.delivery_partner

        if not partner:
            return {
                "total": 0,
                "skip": skip,
                "limit": limit,
                "items": [],
            }

        query = query.filter(
            Order.delivery_partner_id == partner.id
        )

    elif current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    if status_filter:
        query = query.filter(Order.status == status_filter)

    if restaurant_id is not None:
        query = query.filter(
            Order.restaurant_id == restaurant_id
        )

    if from_date is not None:
        query = query.filter(Order.created_at >= from_date)

    if to_date is not None:
        query = query.filter(Order.created_at <= to_date)

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "from_date must be earlier than or equal to to_date"
            ),
        )

    total = query.count()

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
            serialize_order(order)
            for order in orders
        ],
    }


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(
        Order.id == order_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    order_access_check(db, order, current_user)

    return {
        "order": serialize_order(
            order,
            include_otp=(current_user.role == "Customer"),
        ),
        "items": [
            {
                "id": item.id,
                "menu_item_id": item.menu_item_id,
                "item_name": item.item_name,
                "unit_price": float(item.unit_price),
                "quantity": item.quantity,
                "packaging_charge": float(item.packaging_charge),
                "line_total": float(item.line_total),
            }
            for item in order.items
        ],
        "status_history": [
            {
                "old_status": history.old_status,
                "new_status": history.new_status,
                "changed_by": history.changed_by,
                "changed_at": history.changed_at,
            }
            for history in order.status_history
        ],
    }


@router.put("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    try:
        order = (
            db.query(Order)
            .filter(
                Order.id == order_id,
                Order.customer_id == customer.id,
            )
            .with_for_update()
            .first()
        )

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        if order.status not in ("Placed", "Scheduled"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "An order can only be cancelled while "
                    "Placed or Scheduled"
                ),
            )

        record_status(
            db,
            order,
            "Cancelled",
            f"Customer:{customer.id}",
        )

        if order.payment_method == "Online":
            order.payment_status = "Refunded"

        release_coupon_usage(db, order)

        db.commit()
        db.refresh(order)

        return {
            "message": "Order cancelled successfully",
            "order": serialize_order(
                order,
                include_otp=True,
            ),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Cancellation failed",
        )


@router.post("/{order_id}/reorder")
def reorder(
    order_id: int,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    try:
        old_order = db.query(Order).filter(
            Order.id == order_id,
            Order.customer_id == customer.id,
        ).first()

        if not old_order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        cart = db.query(Cart).filter(
            Cart.customer_id == customer.id
        ).first()

        if not cart:
            cart = Cart(customer_id=customer.id)
            db.add(cart)
            db.flush()

        if cart.items and cart.restaurant_id != old_order.restaurant_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Clear your current cart before reordering "
                    "from another restaurant"
                ),
            )

        restaurant = db.query(Restaurant).filter(
            Restaurant.id == old_order.restaurant_id,
            Restaurant.is_active.is_(True),
            Restaurant.is_temporarily_closed.is_(False),
        ).first()

        if not restaurant:
            raise HTTPException(
                status_code=400,
                detail="The original restaurant is unavailable",
            )

        added_items = 0
        skipped_items = 0

        for old_item in old_order.items:
            if old_item.menu_item_id is None:
                skipped_items += 1
                continue

            menu_item = db.query(MenuItem).filter(
                MenuItem.id == old_item.menu_item_id,
                MenuItem.restaurant_id == old_order.restaurant_id,
                MenuItem.is_available.is_(True),
                MenuItem.is_deleted.is_(False),
            ).first()

            if not menu_item:
                skipped_items += 1
                continue

            existing = db.query(CartItem).filter(
                CartItem.cart_id == cart.id,
                CartItem.menu_item_id == menu_item.id,
            ).first()

            if existing:
                existing.quantity = min(
                    10,
                    existing.quantity + old_item.quantity,
                )
            else:
                db.add(
                    CartItem(
                        cart_id=cart.id,
                        menu_item_id=menu_item.id,
                        quantity=min(10, old_item.quantity),
                    )
                )

            added_items += 1

        if added_items:
            cart.restaurant_id = old_order.restaurant_id

        cart.coupon_id = None

        db.commit()

        return {
            "message": "Reorder completed",
            "order_id": old_order.id,
            "added_items": added_items,
            "skipped_items": skipped_items,
            "coupon_reapplied": False,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Reorder failed",
        )

    

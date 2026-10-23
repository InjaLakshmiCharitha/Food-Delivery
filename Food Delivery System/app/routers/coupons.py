from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    User,
    Restaurant,
    Coupon,
    CouponUsage,
    Cart,
    CartItem,
    Order,
)
from app.schemas.coupon import (
    CouponCreate,
    CouponUpdate,
    ApplyCouponRequest,
)
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/coupons", tags=["Coupons"])


def require_role(user: User, allowed_roles: list[str]):
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )


def get_coupon_or_404(db: Session, coupon_id: int) -> Coupon:
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    return coupon


def check_coupon_owner(db: Session, coupon: Coupon, user: User):
    if user.role == "Admin":
        return

    if user.role != "Restaurant Owner":
        raise HTTPException(status_code=403, detail="Access denied")

    if coupon.restaurant_id is None:
        raise HTTPException(
            status_code=403,
            detail="Restaurant owners cannot manage platform coupons",
        )

    restaurant = (
        db.query(Restaurant)
        .filter(
            Restaurant.id == coupon.restaurant_id,
            Restaurant.owner_id == user.id,
        )
        .first()
    )

    if not restaurant:
        raise HTTPException(
            status_code=403,
            detail="You can manage coupons only for your own restaurant",
        )


def get_cart(db: Session, customer_id: int) -> Cart:
    cart = db.query(Cart).filter(Cart.customer_id == customer_id).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    return cart


def calculate_cart_total(db: Session, cart: Cart) -> Decimal:
    items = (
        db.query(CartItem)
        .filter(CartItem.cart_id == cart.id)
        .all()
    )

    total = Decimal("0.00")

    for item in items:
        menu_item = item.menu_item

        if not menu_item or menu_item.is_deleted or not menu_item.is_available:
            raise HTTPException(
                status_code=400,
                detail="Your cart contains an unavailable menu item",
            )

        total += Decimal(str(menu_item.price)) * item.quantity

    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_coupon(
    db: Session,
    coupon: Coupon,
    customer: User,
    cart: Cart,
    item_total: Decimal,
):
    now = datetime.utcnow()

    if not coupon.is_active:
        raise HTTPException(status_code=400, detail="Coupon is inactive")

    if now < coupon.valid_from or now > coupon.valid_to:
        raise HTTPException(
            status_code=400,
            detail="Coupon is not valid at this time",
        )

    if cart.restaurant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Add items to your cart before applying a coupon",
        )

    if coupon.restaurant_id is not None:
        if coupon.restaurant_id != cart.restaurant_id:
            raise HTTPException(
                status_code=400,
                detail="This coupon is not valid for your cart's restaurant",
            )

    if item_total < Decimal(str(coupon.min_order_value)):
        raise HTTPException(
            status_code=400,
            detail=f"Minimum order value is {coupon.min_order_value}",
        )

    if coupon.first_order_only:
        previous_order = (
            db.query(Order)
            .filter(Order.customer_id == customer.id)
            .first()
        )

        if previous_order:
            raise HTTPException(
                status_code=400,
                detail="This coupon is valid only for your first order",
            )

    usage_query = db.query(CouponUsage).filter(
        CouponUsage.coupon_id == coupon.id,
        CouponUsage.is_released.is_(False),
    )

    if coupon.total_usage_limit is not None:
        total_usage = usage_query.count()

        if total_usage >= coupon.total_usage_limit:
            raise HTTPException(
                status_code=400,
                detail="Coupon usage limit has been reached",
            )

    customer_usage = usage_query.filter(
        CouponUsage.customer_id == customer.id
    ).count()

    if customer_usage >= coupon.per_user_limit:
        raise HTTPException(
            status_code=400,
            detail="You have reached the usage limit for this coupon",
        )


def calculate_discount(coupon: Coupon, item_total: Decimal) -> Decimal:
    value = Decimal(str(coupon.discount_value))

    if coupon.discount_type.lower() in ("percentage", "percent"):
        discount = item_total * value / Decimal("100")

        if coupon.max_discount is not None:
            discount = min(discount, Decimal(str(coupon.max_discount)))

    elif coupon.discount_type.lower() == "flat":
        discount = value

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported coupon discount type",
        )

    discount = min(discount, item_total)

    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Create a coupon
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_coupon(
    data: CouponCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Admin", "Restaurant Owner"])

    restaurant_id = data.restaurant_id

    if current_user.role == "Restaurant Owner":
        if restaurant_id is None:
            raise HTTPException(
                status_code=400,
                detail="Restaurant owners must provide restaurant_id",
            )

        restaurant = (
            db.query(Restaurant)
            .filter(
                Restaurant.id == restaurant_id,
                Restaurant.owner_id == current_user.id,
            )
            .first()
        )

        if not restaurant:
            raise HTTPException(
                status_code=403,
                detail="You can create coupons only for your own restaurant",
            )

    elif restaurant_id is None:
        # Admin-created coupons without a restaurant_id are platform coupons.
        pass
    else:
        if not db.query(Restaurant).filter(
            Restaurant.id == restaurant_id
        ).first():
            raise HTTPException(status_code=404, detail="Restaurant not found")

    code = data.code.strip().upper()

    existing = (
        db.query(Coupon)
        .filter(Coupon.code == code)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Coupon code already exists",
        )

    coupon_data = data.model_dump(exclude={"restaurant_id"})
    coupon_data["code"] = code

    coupon = Coupon(
        **coupon_data,
        restaurant_id=restaurant_id,
        created_by=current_user.id,
    )

    db.add(coupon)
    db.commit()
    db.refresh(coupon)

    return coupon



# List coupons with pagination and filters
@router.get("/")
def list_coupons(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    restaurant_id: int | None = Query(default=None, ge=1),
    is_active: bool | None = Query(default=None),
    discount_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ["Admin", "Restaurant Owner"]:
        raise HTTPException(
            status_code=403,
            detail="Only Admins and Restaurant Owners can list managed coupons",
        )

    query = db.query(Coupon)

    # Restaurant owners can view only coupons belonging to their restaurants.
    if current_user.role == "Restaurant Owner":
        owned_restaurants = db.query(Restaurant.id).filter(
            Restaurant.owner_id == current_user.id
        )

        query = query.filter(
            Coupon.restaurant_id.in_(owned_restaurants)
        )

    # Apply optional filters.
    if restaurant_id is not None:
        query = query.filter(Coupon.restaurant_id == restaurant_id)

    if is_active is not None:
        query = query.filter(Coupon.is_active.is_(is_active))

    if discount_type is not None:
        query = query.filter(
            Coupon.discount_type.ilike(discount_type.strip())
        )

    # Count filtered results before pagination.
    total = query.count()

    coupons = (
        query.order_by(Coupon.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": coupons,
    }


# Update a coupon
@router.put("/{coupon_id}")
def update_coupon(
    coupon_id: int,
    data: CouponUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Admin", "Restaurant Owner"])

    coupon = get_coupon_or_404(db, coupon_id)
    check_coupon_owner(db, coupon, current_user)

    updates = data.model_dump(exclude_unset=True)

    new_valid_from = updates.get("valid_from", coupon.valid_from)
    new_valid_to = updates.get("valid_to", coupon.valid_to)

    if new_valid_from and new_valid_to and new_valid_to <= new_valid_from:
        raise HTTPException(
            status_code=400,
            detail="valid_to must be later than valid_from",
        )

    discount_value = updates.get("discount_value", coupon.discount_value)

    if (
        discount_value is not None
        and coupon.discount_type.lower() in ("percentage", "percent")
        and not Decimal("1") <= Decimal(str(discount_value)) <= Decimal("100")
    ):
        raise HTTPException(
            status_code=400,
            detail="Percentage discount must be between 1 and 100",
        )

    for field, value in updates.items():
        setattr(coupon, field, value)

    db.commit()
    db.refresh(coupon)

    return coupon


# Deactivate a coupon
@router.put("/{coupon_id}/deactivate")
def deactivate_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Admin", "Restaurant Owner"])

    coupon = get_coupon_or_404(db, coupon_id)
    check_coupon_owner(db, coupon, current_user)

    coupon.is_active = False

    db.commit()
    db.refresh(coupon)

    return {"message": "Coupon deactivated successfully", "coupon_id": coupon.id}



# View coupons applicable to the customer's cart
@router.get("/available")
def get_available_coupons(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Customer"])

    cart = db.query(Cart).filter(
        Cart.customer_id == current_user.id
    ).first()

    if not cart or not cart.restaurant_id:
        return []

    item_total = calculate_cart_total(db, cart)
    now = datetime.utcnow()

    coupons = (
        db.query(Coupon)
        .filter(
            Coupon.is_active.is_(True),
            Coupon.valid_from <= now,
            Coupon.valid_to >= now,
            (
                (Coupon.restaurant_id.is_(None))
                | (Coupon.restaurant_id == cart.restaurant_id)
            ),
        )
        .order_by(Coupon.id.desc())
        .all()
    )

    available = []

    for coupon in coupons:
        try:
            validate_coupon(
                db, coupon, current_user, cart, item_total
            )
            discount = calculate_discount(coupon, item_total)

            available.append({
                "id": coupon.id,
                "code": coupon.code,
                "description": coupon.description,
                "discount_type": coupon.discount_type,
                "discount_value": float(coupon.discount_value),
                "max_discount": (
                    float(coupon.max_discount)
                    if coupon.max_discount is not None
                    else None
                ),
                "min_order_value": float(coupon.min_order_value),
                "restaurant_id": coupon.restaurant_id,
                "discount_amount": float(discount),
                "item_total_after_discount": float(item_total - discount),
            })
        except HTTPException:
            # Skip coupons that do not qualify for this customer/cart.
            continue

    return available


# Apply a coupon to the cart
@router.post("/apply")
def apply_coupon(
    data: ApplyCouponRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Customer"])

    cart = get_cart(db, current_user.id)

    if not cart.items:
        raise HTTPException(
            status_code=400,
            detail="Add items to your cart before applying a coupon",
        )

    code = data.code.strip().upper()

    coupon = db.query(Coupon).filter(
        Coupon.code == code
    ).first()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    item_total = calculate_cart_total(db, cart)

    validate_coupon(db, coupon, current_user, cart, item_total)

    discount = calculate_discount(coupon, item_total)

    cart.coupon_id = coupon.id

    db.commit()
    db.refresh(cart)

    return {
        "message": "Coupon applied successfully",
        "coupon_code": coupon.code,
        "item_total": float(item_total),
        "discount_amount": float(discount),
        "item_total_after_discount": float(item_total - discount),
    }


# Remove the applied coupon from the cart
@router.delete("/cart")
def remove_cart_coupon(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_role(current_user, ["Customer"])

    cart = db.query(Cart).filter(
        Cart.customer_id == current_user.id
    ).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    if cart.coupon_id is None:
        raise HTTPException(
            status_code=400,
            detail="No coupon is currently applied",
        )

    cart.coupon_id = None

    db.commit()

    return {"message": "Coupon removed from cart successfully"}

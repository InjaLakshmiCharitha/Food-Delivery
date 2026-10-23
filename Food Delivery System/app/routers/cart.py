from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.models import Cart, CartItem, MenuItem, Restaurant, User, Coupon
from app.schemas.cart import (
    CartItemCreate,
    CartItemUpdate,
    CartResponse,
    CartItemResponse,
)
from app.utils.dependencies import get_current_customer

router = APIRouter(prefix="/cart", tags=["Cart Management"])


def get_or_create_cart(db: Session, customer_id: int) -> Cart:
    cart = db.query(Cart).filter(
        Cart.customer_id == customer_id
    ).first()

    if cart is None:
        cart = Cart(customer_id=customer_id)
        db.add(cart)
        db.commit()
        db.refresh(cart)

    return cart


def build_cart_response(db: Session, cart: Cart) -> dict:
    cart_items = (
        db.query(CartItem)
        .options(joinedload(CartItem.menu_item))
        .filter(CartItem.cart_id == cart.id)
        .all()
    )

    items = []
    item_total = 0.0

    for cart_item in cart_items:
        menu_item = cart_item.menu_item
        price = float(menu_item.price)
        line_total = round(price * cart_item.quantity, 2)
        item_total += line_total

        items.append({
            "id": cart_item.id,
            "menu_item_id": menu_item.id,
            "name": menu_item.name,
            "quantity": cart_item.quantity,
            "price": price,
            "line_total": line_total,
        })

    item_total = round(item_total, 2)
    discount = 0.0
    applied_coupon = None

    if cart.coupon_id is not None and item_total > 0:
        coupon = db.query(Coupon).filter(
            Coupon.id == cart.coupon_id,
            Coupon.is_active.is_(True),
        ).first()

        if coupon is not None:
            now = datetime.utcnow()

            coupon_is_valid = (
                coupon.valid_from <= now
                and coupon.valid_to >= now
                and item_total >= float(coupon.min_order_value)
                and (
                    coupon.restaurant_id is None
                    or coupon.restaurant_id == cart.restaurant_id
                )
            )

            if coupon_is_valid:
                if coupon.discount_type.lower() in (
                    "percentage", "percent"
                ):
                    discount = (
                        item_total * float(coupon.discount_value) / 100
                    )

                    if coupon.max_discount is not None:
                        discount = min(
                            discount,
                            float(coupon.max_discount),
                        )
                else:
                    discount = float(coupon.discount_value)

                discount = round(min(discount, item_total), 2)
                applied_coupon = coupon.code
            else:
                # Remove an expired or otherwise invalid applied coupon.
                cart.coupon_id = None

    return {
        "id": cart.id,
        "restaurant_id": cart.restaurant_id,
        "items": items,
        "item_total": item_total,
        "applied_coupon": applied_coupon,
        "discount": discount,
        "item_total_after_discount": round(
            item_total - discount, 2
        ),
    }


@router.get("", response_model=CartResponse)
def get_cart(
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    cart = get_or_create_cart(db, customer.id)
    return build_cart_response(db, cart)


@router.post("/items", response_model=CartResponse)
def add_cart_item(
    data: CartItemCreate,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    cart = get_or_create_cart(db, customer.id)

    menu_item = db.query(MenuItem).filter(
        MenuItem.id == data.menu_item_id,
        MenuItem.is_deleted.is_(False),
        MenuItem.is_available.is_(True),
    ).first()

    if menu_item is None:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found or unavailable",
        )

    restaurant = db.query(Restaurant).filter(
        Restaurant.id == menu_item.restaurant_id,
        Restaurant.is_active.is_(True),
        Restaurant.is_temporarily_closed.is_(False),
    ).first()

    if restaurant is None:
        raise HTTPException(
            status_code=400,
            detail="Restaurant is inactive or temporarily closed",
        )

    if cart.restaurant_id is not None and cart.restaurant_id != menu_item.restaurant_id:
        raise HTTPException(
            status_code=409,
            detail="Your cart has items from another restaurant. Clear the cart to continue",
        )

    existing_item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.menu_item_id == menu_item.id,
    ).first()

    try:
        if existing_item:
            new_quantity = existing_item.quantity + data.quantity

            if new_quantity > 10:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum quantity per item is 10",
                )

            existing_item.quantity = new_quantity
        else:
            cart_item = CartItem(
                cart_id=cart.id,
                menu_item_id=menu_item.id,
                quantity=data.quantity,
            )
            db.add(cart_item)

        cart.restaurant_id = menu_item.restaurant_id
        db.commit()
        db.refresh(cart)

        return build_cart_response(db, cart)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.put("/items/{item_id}", response_model=CartResponse)
def update_cart_item(
    item_id: int,
    data: CartItemUpdate,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    cart = get_or_create_cart(db, customer.id)

    cart_item = db.query(CartItem).filter(
        CartItem.id == item_id,
        CartItem.cart_id == cart.id,
    ).first()

    if cart_item is None:
        raise HTTPException(status_code=404, detail="Cart item not found")

    menu_item = db.query(MenuItem).filter(
        MenuItem.id == cart_item.menu_item_id,
        MenuItem.is_deleted.is_(False),
        MenuItem.is_available.is_(True),
    ).first()

    if menu_item is None:
        raise HTTPException(
            status_code=400,
            detail="This menu item is no longer available",
        )

    cart_item.quantity = data.quantity
    db.commit()
    db.refresh(cart)

    return build_cart_response(db, cart)


@router.delete("/items/{item_id}", response_model=CartResponse)
def remove_cart_item(
    item_id: int,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    cart = get_or_create_cart(db, customer.id)

    cart_item = db.query(CartItem).filter(
        CartItem.id == item_id,
        CartItem.cart_id == cart.id,
    ).first()

    if cart_item is None:
        raise HTTPException(status_code=404, detail="Cart item not found")

    try:
        db.delete(cart_item)
        db.flush()

        remaining_count = db.query(CartItem).filter(
            CartItem.cart_id == cart.id
        ).count()

        if remaining_count == 0:
            cart.restaurant_id = None
            # Level 6 will also clear any applied coupon here.

        db.commit()
        db.refresh(cart)

        return build_cart_response(db, cart)

    except Exception:
        db.rollback()
        raise


@router.delete("")
def clear_cart(
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    cart = get_or_create_cart(db, customer.id)

    try:
        db.query(CartItem).filter(
            CartItem.cart_id == cart.id
        ).delete(synchronize_session=False)

        cart.restaurant_id = None

        # Level 6 will also clear any applied coupon here.
        db.commit()

        return {"message": "Cart cleared successfully"}

    except Exception:
        db.rollback()
        raise

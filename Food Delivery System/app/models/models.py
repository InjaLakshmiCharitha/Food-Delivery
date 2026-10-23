from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(10), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)

    role = Column(String(30), nullable=False, default="Customer")
    is_active = Column(Boolean, default=True, nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    restaurants = relationship("Restaurant", back_populates="owner")
    addresses = relationship("Address", back_populates="customer")
    cart = relationship("Cart", back_populates="customer", uselist=False)
    orders = relationship("Order", back_populates="customer")
    delivery_partner = relationship(
        "DeliveryPartner", back_populates="user", uselist=False
    )
    coupon_usages = relationship("CouponUsage", back_populates="customer")


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    name = Column(String(150), nullable=False)
    cuisine_type = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    opening_time = Column(Time, nullable=False)
    closing_time = Column(Time, nullable=False)

    is_temporarily_closed = Column(Boolean, default=False, nullable=False)
    delivery_radius_km = Column(Float, default=5.0, nullable=False)
    min_order_value = Column(Numeric(10, 2), default=0, nullable=False)
    avg_preparation_minutes = Column(Integer, default=30, nullable=False)
    average_rating = Column(Float, default=0.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    owner = relationship("User", back_populates="restaurants")
    categories = relationship("MenuCategory", back_populates="restaurant")
    menu_items = relationship("MenuItem", back_populates="restaurant")
    orders = relationship("Order", back_populates="restaurant")
    coupons = relationship("Coupon", back_populates="restaurant")
    ratings = relationship("Rating", back_populates="restaurant")


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=False
    )

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    restaurant = relationship("Restaurant", back_populates="categories")
    menu_items = relationship("MenuItem", back_populates="category")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=False
    )
    category_id = Column(
        Integer, ForeignKey("menu_categories.id"), nullable=False
    )

    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    is_veg = Column(Boolean, default=True, nullable=False)
    packaging_charge = Column(Numeric(10, 2), default=0, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    restaurant = relationship("Restaurant", back_populates="menu_items")
    category = relationship("MenuCategory", back_populates="menu_items")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    label = Column(String(30), default="Home", nullable=False)
    address_line = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    pincode = Column(String(6), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    customer = relationship("User", back_populates="addresses")
    orders = relationship("Order", back_populates="address")


class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=True
    )
    coupon_id = Column(Integer, ForeignKey("coupons.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    customer = relationship("User", back_populates="cart")
    restaurant = relationship("Restaurant")
    coupon = relationship("Coupon")
    items = relationship("CartItem", back_populates="cart",
                         cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("carts.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    cart = relationship("Cart", back_populates="items")
    menu_item = relationship("MenuItem")


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=True
    )
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    code = Column(String(50), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    discount_type = Column(String(20), nullable=False)
    discount_value = Column(Numeric(10, 2), nullable=False)
    max_discount = Column(Numeric(10, 2), nullable=True)
    min_order_value = Column(Numeric(10, 2), default=0, nullable=False)

    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime, nullable=False)

    total_usage_limit = Column(Integer, nullable=True)
    per_user_limit = Column(Integer, default=1, nullable=False)
    first_order_only = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    restaurant = relationship("Restaurant", back_populates="coupons")
    usages = relationship("CouponUsage", back_populates="coupon")


class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id = Column(Integer, primary_key=True, index=True)
    coupon_id = Column(Integer, ForeignKey("coupons.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)

    discount_amount = Column(Numeric(10, 2), nullable=False)
    is_released = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    coupon = relationship("Coupon", back_populates="usages")
    customer = relationship("User", back_populates="coupon_usages")
    order = relationship("Order", back_populates="coupon_usage")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(30), unique=True, index=True, nullable=False)

    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=False
    )
    address_id = Column(Integer, ForeignKey("addresses.id"), nullable=False)
    delivery_partner_id = Column(
        Integer, ForeignKey("delivery_partners.id"), nullable=True
    )

    item_total = Column(Numeric(10, 2), nullable=False)
    coupon_code = Column(String(50), nullable=True)
    discount_amount = Column(Numeric(10, 2), default=0, nullable=False)
    packaging_charges = Column(Numeric(10, 2), default=0, nullable=False)
    delivery_fee = Column(Numeric(10, 2), default=20, nullable=False)
    platform_fee = Column(Numeric(10, 2), default=5, nullable=False)
    gst_amount = Column(Numeric(10, 2), default=0, nullable=False)
    tip_amount = Column(Numeric(10, 2), default=0, nullable=False)
    grand_total = Column(Numeric(10, 2), nullable=False)

    payment_method = Column(String(20), nullable=False, default="COD")
    payment_status = Column(String(20), default="Pending", nullable=False)
    status = Column(String(30), default="Placed", nullable=False)

    distance_km = Column(Float, nullable=True)
    delivery_otp = Column(String(4), nullable=False)
    otp_attempts = Column(Integer, default=0, nullable=False)
    delivery_locked = Column(Boolean, default=False, nullable=False)

    rejection_reason = Column(Text, nullable=True)
    estimated_preparation_minutes = Column(Integer, nullable=True)
    placed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    customer = relationship("User", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    address = relationship("Address", back_populates="orders")
    delivery_partner = relationship(
        "DeliveryPartner", back_populates="orders"
    )

    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    status_history = relationship(
        "OrderStatusHistory", back_populates="order",
        cascade="all, delete-orphan"
    )
    coupon_usage = relationship(
        "CouponUsage", back_populates="order", uselist=False
    )
    delivery_offers = relationship(
        "DeliveryOffer", back_populates="order"
    )
    rating = relationship(
        "Rating", back_populates="order", uselist=False
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)

    item_name = Column(String(150), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    packaging_charge = Column(Numeric(10, 2), default=0, nullable=False)
    line_total = Column(Numeric(10, 2), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    old_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=False)
    changed_by = Column(String(100), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    order = relationship("Order", back_populates="status_history")


class DeliveryPartner(Base):
    __tablename__ = "delivery_partners"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    vehicle_type = Column(String(30), nullable=False)
    vehicle_number = Column(String(30), unique=True, nullable=False)

    is_online = Column(Boolean, default=False, nullable=False)
    current_latitude = Column(Float, nullable=True)
    current_longitude = Column(Float, nullable=True)
    last_location_at = Column(DateTime, nullable=True)
    is_approved = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="delivery_partner")
    orders = relationship("Order", back_populates="delivery_partner")
    offers = relationship("DeliveryOffer", back_populates="partner")


class DeliveryOffer(Base):
    __tablename__ = "delivery_offers"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    partner_id = Column(
        Integer, ForeignKey("delivery_partners.id"), nullable=False
    )

    status = Column(String(20), default="Pending", nullable=False)
    offered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    order = relationship("Order", back_populates="delivery_offers")
    partner = relationship("DeliveryPartner", back_populates="offers")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(150), nullable=False)
    message = Column(String(500), nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer, ForeignKey("orders.id"), unique=True, nullable=False
    )
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id"), nullable=False
    )
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    restaurant_rating = Column(Integer, nullable=False)
    partner_rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    order = relationship("Order", back_populates="rating")
    restaurant = relationship("Restaurant", back_populates="ratings")
    customer = relationship("User")

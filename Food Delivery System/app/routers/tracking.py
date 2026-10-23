from datetime import datetime
from math import ceil

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, Order, Restaurant, DeliveryPartner
from app.utils.security import decode_access_token
from app.utils.location import calculate_distance_km
from app.websockets.connection_manager import manager
from pathlib import Path
from fastapi.responses import FileResponse

router = APIRouter(tags=["Real-Time Tracking"])


def get_user_from_token(db: Session, token: str):
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        return None

    user = db.query(User).filter(User.id == user_id).first()

    if not user or not user.is_active:
        return None

    if user.role in ["Restaurant Owner", "Delivery Partner"]:
        if not user.is_approved:
            return None

    return user


def order_access_allowed(db: Session, order: Order, user: User) -> bool:
    if user.role == "Admin":
        return True

    if user.role == "Customer":
        return order.customer_id == user.id

    if user.role == "Restaurant Owner":
        restaurant = db.query(Restaurant).filter(
            Restaurant.id == order.restaurant_id,
            Restaurant.owner_id == user.id,
        ).first()
        return restaurant is not None

    if user.role == "Delivery Partner":
        partner = db.query(DeliveryPartner).filter(
            DeliveryPartner.user_id == user.id
        ).first()
        return bool(
            partner and order.delivery_partner_id == partner.id
        )

    return False


def tracking_payload(db: Session, order: Order) -> dict:
    partner_data = None
    remaining_km = None
    eta_minutes = None

    if order.delivery_partner_id:
        partner = db.query(DeliveryPartner).filter(
            DeliveryPartner.id == order.delivery_partner_id
        ).first()

        if partner:
            partner_user = db.query(User).filter(
                User.id == partner.user_id
            ).first()

            partner_data = {
                "name": partner_user.full_name if partner_user else None,
                "vehicle_type": partner.vehicle_type,
                "vehicle_number": partner.vehicle_number,
                "latitude": partner.current_latitude,
                "longitude": partner.current_longitude,
                "last_location_at": (
                    partner.last_location_at.isoformat()
                    if partner.last_location_at else None
                ),
            }

            address = order.address

            if (
                address
                and address.latitude is not None
                and address.longitude is not None
                and partner.current_latitude is not None
                and partner.current_longitude is not None
            ):
                remaining_km = calculate_distance_km(
                    partner.current_latitude,
                    partner.current_longitude,
                    address.latitude,
                    address.longitude,
                )

                # Approximate travel ETA at 20 km/h.
                eta_minutes = ceil((remaining_km / 20) * 60)

    return {
        "event": "order_tracking",
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "partner": partner_data,
        "distance_remaining_km": remaining_km,
        "estimated_arrival_minutes": eta_minutes,
        "updated_at": datetime.utcnow().isoformat(),
    }


@router.websocket("/ws/orders/{order_id}")
async def order_tracking(
    websocket: WebSocket,
    order_id: int,
    token: str = Query(...),
):
    db_generator = get_db()
    db = next(db_generator)
    room = f"order_{order_id}"

    try:
        user = get_user_from_token(db, token)

        if not user:
            await websocket.close(code=1008, reason="Invalid access token")
            return

        order = db.query(Order).filter(Order.id == order_id).first()

        if not order:
            await websocket.close(code=1008, reason="Order not found")
            return

        if not order_access_allowed(db, order, user):
            await websocket.close(code=1008, reason="Access denied")
            return

        await manager.connect(websocket, room)
        await websocket.send_json(tracking_payload(db, order))

        while True:
            data = await websocket.receive_json()

            # Only the assigned delivery partner may send location updates.
            if data.get("type") != "location_update":
                await websocket.send_json({
                    "event": "error",
                    "message": "Unsupported WebSocket message",
                })
                continue

            if user.role != "Delivery Partner":
                await websocket.send_json({
                    "event": "error",
                    "message": "Only the assigned partner can send location updates",
                })
                continue

            db.expire_all()
            order = db.query(Order).filter(
                Order.id == order_id
            ).first()

            if (
                not order
                or not order_access_allowed(db, order, user)
            ):
                await websocket.send_json({
                    "event": "error",
                    "message": "You are not assigned to this order",
                })
                continue

            if order.status in ["Delivered", "Cancelled"]:
                await websocket.send_json({
                    "event": "error",
                    "message": "Location updates are not allowed for completed orders",
                })
                continue

            try:
                latitude = float(data["latitude"])
                longitude = float(data["longitude"])

                if not -90 <= latitude <= 90:
                    raise ValueError()

                if not -180 <= longitude <= 180:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                await websocket.send_json({
                    "event": "error",
                    "message": "Valid latitude and longitude are required",
                })
                continue

            partner = db.query(DeliveryPartner).filter(
                DeliveryPartner.user_id == user.id
            ).first()

            if not partner:
                continue

            partner.current_latitude = latitude
            partner.current_longitude = longitude
            partner.last_location_at = datetime.utcnow()
            db.commit()
            db.refresh(order)

            await manager.broadcast(
                room,
                tracking_payload(db, order),
            )

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, room)
        db.close()
        db_generator.close()



async def authenticated_room(
    websocket: WebSocket,
    token: str,
    room: str,
    role: str,
):
    db_generator = get_db()
    db = next(db_generator)
    user = None
    connected_room = None

    try:
        user = get_user_from_token(db, token)

        if not user or user.role != role:
            await websocket.close(
                code=1008,
                reason="Invalid token or insufficient permissions",
            )
            return

        if role == "Restaurant Owner":
            connected_room = f"restaurant_user_{user.id}"

        elif role == "Delivery Partner":
            partner = db.query(DeliveryPartner).filter(
                DeliveryPartner.user_id == user.id
            ).first()

            if not partner or not partner.is_approved:
                await websocket.close(
                    code=1008,
                    reason="Approved partner profile required",
                )
                return

            connected_room = f"partner_user_{user.id}"

        else:
            await websocket.close(
                code=1008,
                reason="Role not allowed",
            )
            return

        await manager.connect(websocket, connected_room)

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    finally:
        if connected_room is not None:
            manager.disconnect(websocket, connected_room)

        db.close()
        db_generator.close()



@router.websocket("/ws/restaurant")
async def restaurant_alerts(
    websocket: WebSocket,
    token: str = Query(...),
):
    await authenticated_room(
        websocket, token, "restaurant", "Restaurant Owner"
    )


@router.websocket("/ws/partner")
async def partner_alerts(
    websocket: WebSocket,
    token: str = Query(...),
):
    await authenticated_room(
        websocket, token, "partner", "Delivery Partner"
    )


@router.get("/tracking-test", include_in_schema=False)
def tracking_test_page():
    html_file = Path(__file__).resolve().parents[2] / "static" / "tracking_test.html"
    return FileResponse(html_file, media_type="text/html")
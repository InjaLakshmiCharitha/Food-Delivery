from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.models import Restaurant, MenuCategory, MenuItem, User
from app.schemas.restaurant import (
    RestaurantCreate,
    RestaurantUpdate,
    RestaurantResponse,
    OpenStatusUpdate,
    CategoryCreate,
    CategoryResponse,
    MenuItemCreate,
    MenuItemUpdate,
    MenuAvailabilityUpdate,
    MenuItemResponse,
    MenuCategoryGroup,
)
from app.utils.dependencies import (
    get_current_restaurant_owner,
)

router = APIRouter(prefix="/restaurants", tags=["Restaurants"])


def restaurant_is_open(restaurant: Restaurant) -> bool:
    current_time = datetime.now().time()
    return (
        restaurant.is_active
        and not restaurant.is_temporarily_closed
        and restaurant.opening_time <= current_time <= restaurant.closing_time
    )


def get_owned_restaurant(
    restaurant_id: int,
    db: Session,
    owner: User,
) -> Restaurant:
    restaurant = (
        db.query(Restaurant)
        .filter(
            Restaurant.id == restaurant_id,
            Restaurant.owner_id == owner.id,
        )
        .first()
    )

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant not found or you do not own it",
        )

    return restaurant


def restaurant_response(restaurant: Restaurant) -> dict:
    return {
        "id": restaurant.id,
        "owner_id": restaurant.owner_id,
        "name": restaurant.name,
        "cuisine_type": restaurant.cuisine_type,
        "address": restaurant.address,
        "latitude": restaurant.latitude,
        "longitude": restaurant.longitude,
        "opening_time": restaurant.opening_time,
        "closing_time": restaurant.closing_time,
        "is_temporarily_closed": restaurant.is_temporarily_closed,
        "delivery_radius_km": restaurant.delivery_radius_km,
        "min_order_value": restaurant.min_order_value,
        "avg_preparation_minutes": restaurant.avg_preparation_minutes,
        "average_rating": restaurant.average_rating,
        "is_active": restaurant.is_active,
        "is_open": restaurant_is_open(restaurant),
    }


@router.post(
    "",
    response_model=RestaurantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_restaurant(
    data: RestaurantCreate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurant = Restaurant(
        owner_id=owner.id,
        **data.model_dump(),
    )

    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)

    return restaurant_response(restaurant)


@router.get("/me", response_model=list[RestaurantResponse])
def get_my_restaurants(
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurants = (
        db.query(Restaurant)
        .filter(Restaurant.owner_id == owner.id)
        .all()
    )

    return [restaurant_response(r) for r in restaurants]


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
def get_restaurant(
    restaurant_id: int,
    db: Session = Depends(get_db),
):
    restaurant = (
        db.query(Restaurant)
        .filter(
            Restaurant.id == restaurant_id,
            Restaurant.is_active.is_(True),
        )
        .first()
    )

    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    return restaurant_response(restaurant)


@router.put("/{restaurant_id}", response_model=RestaurantResponse)
def update_restaurant(
    restaurant_id: int,
    data: RestaurantUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurant = get_owned_restaurant(restaurant_id, db, owner)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(restaurant, field, value)

    db.commit()
    db.refresh(restaurant)

    return restaurant_response(restaurant)


@router.put("/{restaurant_id}/open-status", response_model=RestaurantResponse)
def update_open_status(
    restaurant_id: int,
    data: OpenStatusUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurant = get_owned_restaurant(restaurant_id, db, owner)

    restaurant.is_temporarily_closed = data.is_temporarily_closed

    db.commit()
    db.refresh(restaurant)

    return restaurant_response(restaurant)


@router.post(
    "/{restaurant_id}/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    restaurant_id: int,
    data: CategoryCreate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurant = get_owned_restaurant(restaurant_id, db, owner)

    category = MenuCategory(
        restaurant_id=restaurant.id,
        name=data.name,
        description=data.description,
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    return category


@router.post(
    "/{restaurant_id}/menu-items",
    response_model=MenuItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_menu_item(
    restaurant_id: int,
    data: MenuItemCreate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    restaurant = get_owned_restaurant(restaurant_id, db, owner)

    category = (
        db.query(MenuCategory)
        .filter(
            MenuCategory.id == data.category_id,
            MenuCategory.restaurant_id == restaurant.id,
        )
        .first()
    )

    if category is None:
        raise HTTPException(
            status_code=400,
            detail="Category does not belong to this restaurant",
        )

    item = MenuItem(
        restaurant_id=restaurant.id,
        **data.model_dump(),
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return item


@router.get("/{restaurant_id}/menu", response_model=list[MenuCategoryGroup])
def get_restaurant_menu(
    restaurant_id: int,
    db: Session = Depends(get_db),
):
    restaurant = (
        db.query(Restaurant)
        .filter(
            Restaurant.id == restaurant_id,
            Restaurant.is_active.is_(True),
        )
        .first()
    )

    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    categories = (
        db.query(MenuCategory)
        .options(joinedload(MenuCategory.menu_items))
        .filter(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.id)
        .all()
    )

    result = []

    for category in categories:
        items = [
            item
            for item in category.menu_items
            if not item.is_deleted
        ]

        result.append({
            "category_id": category.id,
            "category_name": category.name,
            "items": items,
        })

    return result


@router.put("/menu-items/{item_id}", response_model=MenuItemResponse)
def update_menu_item(
    item_id: int,
    data: MenuItemUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    item = (
        db.query(MenuItem)
        .join(Restaurant)
        .filter(
            MenuItem.id == item_id,
            MenuItem.is_deleted.is_(False),
            Restaurant.owner_id == owner.id,
        )
        .first()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    updates = data.model_dump(exclude_unset=True)

    if "category_id" in updates:
        category = (
            db.query(MenuCategory)
            .filter(
                MenuCategory.id == updates["category_id"],
                MenuCategory.restaurant_id == item.restaurant_id,
            )
            .first()
        )

        if category is None:
            raise HTTPException(
                status_code=400,
                detail="Category does not belong to this restaurant",
            )

    for field, value in updates.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)

    return item


@router.put(
    "/menu-items/{item_id}/availability",
    response_model=MenuItemResponse,
)
def update_menu_item_availability(
    item_id: int,
    data: MenuAvailabilityUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    item = (
        db.query(MenuItem)
        .join(Restaurant)
        .filter(
            MenuItem.id == item_id,
            MenuItem.is_deleted.is_(False),
            Restaurant.owner_id == owner.id,
        )
        .first()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    item.is_available = data.is_available

    db.commit()
    db.refresh(item)

    return item


@router.delete("/menu-items/{item_id}")
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(get_current_restaurant_owner),
):
    item = (
        db.query(MenuItem)
        .join(Restaurant)
        .filter(
            MenuItem.id == item_id,
            MenuItem.is_deleted.is_(False),
            Restaurant.owner_id == owner.id,
        )
        .first()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    item.is_deleted = True
    item.is_available = False

    db.commit()

    return {"message": "Menu item deleted successfully"}


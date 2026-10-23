
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Address, Order, User
from app.schemas.address import (
    AddressCreate,
    AddressUpdate,
    AddressResponse,
)
from app.utils.dependencies import get_current_customer

router = APIRouter(
    prefix="/addresses",
    tags=["Address Management"],
)


def get_customer_address(
    address_id: int,
    customer_id: int,
    db: Session,
) -> Address:
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.customer_id == customer_id,
    ).first()

    if address is None:
        raise HTTPException(
            status_code=404,
            detail="Address not found",
        )

    return address


def clear_default_addresses(
    db: Session,
    customer_id: int,
    except_id: int | None = None,
) -> None:
    query = db.query(Address).filter(
        Address.customer_id == customer_id
    )

    if except_id is not None:
        query = query.filter(Address.id != except_id)

    query.update(
        {Address.is_default: False},
        synchronize_session=False,
    )


@router.post(
    "",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_address(
    data: AddressCreate,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    try:
        count = db.query(Address).filter(
            Address.customer_id == customer.id
        ).count()

        address_data = data.model_dump()

        # The first address is automatically the default.
        if count == 0:
            address_data["is_default"] = True

        if address_data["is_default"]:
            clear_default_addresses(db, customer.id)

        address = Address(
            customer_id=customer.id,
            **address_data,
        )

        db.add(address)
        db.commit()
        db.refresh(address)
        return address

    except Exception:
        db.rollback()
        raise


@router.get("", response_model=list[AddressResponse])
def get_addresses(
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    return db.query(Address).filter(
        Address.customer_id == customer.id
    ).order_by(Address.id).all()


@router.put(
    "/{address_id}",
    response_model=AddressResponse,
)
def update_address(
    address_id: int,
    data: AddressUpdate,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    address = get_customer_address(
        address_id, customer.id, db
    )

    updates = data.model_dump(exclude_unset=True)

    if any(value is None for value in updates.values()):
        raise HTTPException(
            status_code=400,
            detail="Address fields cannot be null",
        )

    try:
        if updates.get("is_default") is True:
            clear_default_addresses(
                db, customer.id, except_id=address.id
            )

        for field, value in updates.items():
            setattr(address, field, value)

        db.commit()
        db.refresh(address)
        return address

    except Exception:
        db.rollback()
        raise


@router.delete("/{address_id}")
def delete_address(
    address_id: int,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    address = get_customer_address(
        address_id, customer.id, db
    )

    order_exists = db.query(Order.id).filter(
        Order.address_id == address.id
    ).first()

    if order_exists:
        raise HTTPException(
            status_code=409,
            detail="This address is used by an order and cannot be deleted",
        )

    was_default = address.is_default

    try:
        db.delete(address)
        db.flush()

        if was_default:
            replacement = db.query(Address).filter(
                Address.customer_id == customer.id
            ).order_by(Address.id).first()

            if replacement:
                replacement.is_default = True

        db.commit()
        return {"message": "Address deleted successfully"}

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{address_id}/default",
    response_model=AddressResponse,
)
def set_default_address(
    address_id: int,
    db: Session = Depends(get_db),
    customer: User = Depends(get_current_customer),
):
    address = get_customer_address(
        address_id, customer.id, db
    )

    try:
        clear_default_addresses(
            db, customer.id, except_id=address.id
        )
        address.is_default = True

        db.commit()
        db.refresh(address)
        return address

    except Exception:
        db.rollback()
        raise

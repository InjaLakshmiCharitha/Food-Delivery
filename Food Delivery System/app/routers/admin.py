
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User
from app.utils.dependencies import get_current_admin

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


@router.put("/users/{user_id}/approve")
def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if user.role not in ["Restaurant Owner", "Delivery Partner"]:
        raise HTTPException(
            status_code=400,
            detail="Only restaurant owners and delivery partners require approval",
        )

    if user.is_approved:
        return {
            "message": "User is already approved",
            "user_id": user.id,
            "role": user.role,
            "is_approved": user.is_approved,
        }

    user.is_approved = True
    db.commit()
    db.refresh(user)

    return {
        "message": "User approved successfully",
        "user_id": user.id,
        "role": user.role,
        "is_approved": user.is_approved,
    }

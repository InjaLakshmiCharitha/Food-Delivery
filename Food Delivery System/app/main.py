
from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler

from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.restaurants import router as restaurants_router
from app.routers.nearby import router as nearby_router
from app.routers.addresses import router as addresses_router
from app.routers.cart import router as cart_router
from app.routers.coupons import router as coupons_router
from app.routers.orders import router as orders_router
from app.routers.restaurant_orders import router as restaurant_orders_router
from app.routers.delivery import router as delivery_router
from app.routers.tracking import router as tracking_router
from app.routers.ratings import router as ratings_router
from app.routers.reports import router as reports_router

from app.jobs import (
    auto_reject_orders,
    expire_delivery_offers,
    retry_unassigned_orders_job,
    mark_inactive_partners_offline,
    deactivate_expired_coupons,
    process_scheduled_orders,
)

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        auto_reject_orders,
        trigger="interval",
        minutes=1,
        id="auto_reject_orders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        expire_delivery_offers,
        trigger="interval",
        seconds=10,
        id="expire_delivery_offers",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        retry_unassigned_orders_job,
        trigger="interval",
        minutes=1,
        id="retry_unassigned_orders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        mark_inactive_partners_offline,
        trigger="interval",
        minutes=5,
        id="mark_inactive_partners_offline",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        deactivate_expired_coupons,
        trigger="cron",
        hour=0,
        minute=0,
        id="deactivate_expired_coupons",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        process_scheduled_orders,
        trigger="interval",
        seconds=30,
        id="process_scheduled_orders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="Food Delivery System",
    description="Food Delivery System Backend API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(restaurants_router)
app.include_router(nearby_router)
app.include_router(addresses_router)
app.include_router(cart_router)
app.include_router(coupons_router)
app.include_router(orders_router)
app.include_router(restaurant_orders_router)
app.include_router(delivery_router)
app.include_router(tracking_router)
app.include_router(ratings_router)
app.include_router(reports_router)

@app.get("/")
def home():
    return {"message": "Food Delivery System API is running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}




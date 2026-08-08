from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    catalog,
    chats,
    complaints,
    documents,
    orders,
    placements,
    providers,
    reviews,
    users,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(catalog.router)
router.include_router(providers.router)
router.include_router(orders.router)
router.include_router(placements.router)
router.include_router(reviews.router)
router.include_router(chats.router)
router.include_router(complaints.router)
router.include_router(documents.router)
router.include_router(admin.router)

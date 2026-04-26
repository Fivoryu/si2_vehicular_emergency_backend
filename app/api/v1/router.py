from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.clients import router as clients_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.emergencies import router as emergencies_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.system import router as system_router
from app.api.v1.endpoints.workshops import router as workshops_router

api_router = APIRouter()
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(clients_router, prefix="/clients", tags=["clients"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(emergencies_router, prefix="/emergencies", tags=["emergencies"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(workshops_router, prefix="/workshops", tags=["workshops"])

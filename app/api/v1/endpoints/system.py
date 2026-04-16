from fastapi import APIRouter

from app.schemas.system import SystemInfo
from app.services.aws import aws_service

router = APIRouter()


@router.get("/info", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    return SystemInfo(
        service="backend",
        environment=aws_service.environment_name,
        aws_region=aws_service.region,
        storage_bucket=aws_service.bucket_name,
    )

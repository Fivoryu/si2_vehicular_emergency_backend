from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.user import User, Vehicle, VehicleType
from app.schemas.user import VehicleCreate, VehicleResponse

router = APIRouter()


@router.post("/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def register_vehicle(
    payload: VehicleCreate,
    session: AsyncSession = Depends(get_db_session),
) -> VehicleResponse:
    owner = await session.get(User, payload.owner_id)
    if not owner or not owner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado.")

    duplicate_plate = await session.scalar(select(Vehicle).where(Vehicle.plate == payload.plate))
    if duplicate_plate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La placa ya está registrada.")
    vehicle_type = None
    if payload.vehicle_type:
        try:
            vehicle_type = VehicleType(payload.vehicle_type)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tipo de vehículo inválido.") from exc

    vehicle = Vehicle(
        owner_id=payload.owner_id,
        plate=payload.plate,
        brand=payload.brand,
        model=payload.model,
        year=payload.year,
        color=payload.color,
        vehicle_type=vehicle_type,
    )
    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)

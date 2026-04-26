from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.models.user import Account, AccountRoleName, User, Vehicle, VehicleType
from app.schemas.user import VehicleCreate, VehicleResponse

router = APIRouter()


@router.post("/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def register_vehicle(
    payload: VehicleCreate,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(require_roles(AccountRoleName.CLIENT, AccountRoleName.ADMIN)),
) -> VehicleResponse:
    owner = await session.get(User, payload.owner_id)
    if not owner or not owner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado.")
    if current_account.primary_role == AccountRoleName.CLIENT.value and owner.account_id != current_account.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes registrar vehículos para otro cliente.")

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


@router.get("/vehicles", response_model=list[VehicleResponse])
async def list_my_vehicles(
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(require_roles(AccountRoleName.CLIENT)),
) -> list[VehicleResponse]:
    client = await session.scalar(
        select(User)
        .options(selectinload(User.vehicles))
        .where(User.account_id == current_account.id)
    )
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado.")
    return [VehicleResponse.model_validate(vehicle) for vehicle in client.vehicles]


@router.get("/{client_id}/vehicles", response_model=list[VehicleResponse])
async def list_client_vehicles(
    client_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(require_roles(AccountRoleName.CLIENT, AccountRoleName.ADMIN)),
) -> list[VehicleResponse]:
    client = await session.scalar(
        select(User)
        .options(selectinload(User.vehicles))
        .where(User.id == client_id)
    )
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado.")
    if current_account.primary_role == AccountRoleName.CLIENT.value and client.account_id != current_account.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes consultar vehículos de otro cliente.")
    return [VehicleResponse.model_validate(vehicle) for vehicle in client.vehicles]

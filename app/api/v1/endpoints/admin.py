from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.models.user import (
    Account,
    AccountRole,
    AccountRoleName,
    AdminEvent,
    Administrator,
    Role,
    Workshop,
    WorkshopAvailabilityState,
)

router = APIRouter()


class AccountAdminItem(BaseModel):
    id: int
    email: str
    phone: str | None
    role: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_access_at: datetime | None


class AccountStatusUpdate(BaseModel):
    is_active: bool
    notes: str | None = Field(default=None, max_length=500)


class WorkshopAdminItem(BaseModel):
    id: int
    trade_name: str
    city: str
    email: str
    is_active: bool
    is_available: bool
    is_admin_approved: bool
    availability_state: str | None
    approval_notes: str | None
    registered_at: datetime


class WorkshopApprovalUpdate(BaseModel):
    is_admin_approved: bool
    notes: str | None = Field(default=None, max_length=500)


class AdminEventItem(BaseModel):
    id: int
    admin_id: int | None
    entity: str
    entity_id: int | None
    action: str
    notes: str | None
    event_at: datetime


async def get_admin_profile(session: AsyncSession, account: Account) -> Administrator | None:
    return await session.scalar(select(Administrator).where(Administrator.account_id == account.id))


async def add_admin_event(
    *,
    session: AsyncSession,
    current_account: Account,
    entity: str,
    entity_id: int | None,
    action: str,
    notes: str | None = None,
) -> None:
    admin = await get_admin_profile(session, current_account)
    session.add(
        AdminEvent(
            admin_id=admin.id if admin else None,
            entity=entity,
            entity_id=entity_id,
            action=action,
            notes=notes,
        )
    )


@router.get("/accounts", response_model=list[AccountAdminItem])
async def list_accounts(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _current_account: Account = Depends(require_roles(AccountRoleName.ADMIN)),
) -> list[AccountAdminItem]:
    accounts = (
        await session.scalars(
            select(Account)
            .options(selectinload(Account.account_roles).selectinload(AccountRole.role))
            .order_by(Account.created_at.desc(), Account.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        AccountAdminItem(
            id=account.id,
            email=account.email,
            phone=account.phone,
            role=account.primary_role,
            is_active=account.is_active,
            is_verified=account.is_verified,
            created_at=account.created_at,
            last_access_at=account.last_access_at,
        )
        for account in accounts
    ]


@router.patch("/accounts/{account_id}/status", response_model=AccountAdminItem)
async def update_account_status(
    account_id: int,
    payload: AccountStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(require_roles(AccountRoleName.ADMIN)),
) -> AccountAdminItem:
    account = await session.scalar(
        select(Account)
        .options(selectinload(Account.account_roles).selectinload(AccountRole.role))
        .where(Account.id == account_id)
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada.")
    if account.id == current_account.id and not payload.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No puedes desactivar tu propia cuenta.")
    account.is_active = payload.is_active
    account.updated_at = datetime.utcnow()
    await add_admin_event(
        session=session,
        current_account=current_account,
        entity="account",
        entity_id=account.id,
        action="activate" if payload.is_active else "deactivate",
        notes=payload.notes,
    )
    await session.commit()
    return AccountAdminItem(
        id=account.id,
        email=account.email,
        phone=account.phone,
        role=account.primary_role,
        is_active=account.is_active,
        is_verified=account.is_verified,
        created_at=account.created_at,
        last_access_at=account.last_access_at,
    )


@router.get("/workshops", response_model=list[WorkshopAdminItem])
async def list_workshops_for_admin(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _current_account: Account = Depends(require_roles(AccountRoleName.ADMIN)),
) -> list[WorkshopAdminItem]:
    workshops = (
        await session.scalars(
            select(Workshop)
            .options(selectinload(Workshop.availability_state))
            .order_by(Workshop.registered_at.desc(), Workshop.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        WorkshopAdminItem(
            id=workshop.id,
            trade_name=workshop.trade_name,
            city=workshop.city,
            email=workshop.email,
            is_active=workshop.is_active,
            is_available=workshop.is_available,
            is_admin_approved=workshop.is_admin_approved,
            availability_state=workshop.availability_state.name if workshop.availability_state else None,
            approval_notes=workshop.approval_notes,
            registered_at=workshop.registered_at,
        )
        for workshop in workshops
    ]


@router.patch("/workshops/{workshop_id}/approval", response_model=WorkshopAdminItem)
async def update_workshop_approval(
    workshop_id: int,
    payload: WorkshopApprovalUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(require_roles(AccountRoleName.ADMIN)),
) -> WorkshopAdminItem:
    workshop = await session.scalar(
        select(Workshop)
        .options(selectinload(Workshop.availability_state))
        .where(Workshop.id == workshop_id)
    )
    if not workshop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no encontrado.")
    workshop.is_admin_approved = payload.is_admin_approved
    workshop.approved_at = datetime.utcnow() if payload.is_admin_approved else None
    workshop.approval_notes = payload.notes
    workshop.updated_at = datetime.utcnow()
    if payload.is_admin_approved and not workshop.availability_state:
        available_state = await session.scalar(select(WorkshopAvailabilityState).where(WorkshopAvailabilityState.name == "disponible"))
        if available_state:
            workshop.availability_state_id = available_state.id
    await add_admin_event(
        session=session,
        current_account=current_account,
        entity="workshop",
        entity_id=workshop.id,
        action="approve" if payload.is_admin_approved else "unapprove",
        notes=payload.notes,
    )
    await session.commit()
    await session.refresh(workshop)
    return WorkshopAdminItem(
        id=workshop.id,
        trade_name=workshop.trade_name,
        city=workshop.city,
        email=workshop.email,
        is_active=workshop.is_active,
        is_available=workshop.is_available,
        is_admin_approved=workshop.is_admin_approved,
        availability_state=workshop.availability_state.name if workshop.availability_state else None,
        approval_notes=workshop.approval_notes,
        registered_at=workshop.registered_at,
    )


@router.get("/events", response_model=list[AdminEventItem])
async def list_admin_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _current_account: Account = Depends(require_roles(AccountRoleName.ADMIN)),
) -> list[AdminEventItem]:
    events = (
        await session.scalars(
            select(AdminEvent)
            .order_by(AdminEvent.event_at.desc(), AdminEvent.id.desc())
            .limit(limit)
        )
    ).all()
    return [AdminEventItem.model_validate(event, from_attributes=True) for event in events]

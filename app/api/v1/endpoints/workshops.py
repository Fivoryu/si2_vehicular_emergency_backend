from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.core.security import hash_password
from app.models.emergency import DailyMetric, Incident, IncidentStatus, Payment, Priority
from app.models.user import (
    Account,
    AccountRole,
    AccountRoleName,
    Specialty,
    User,
    Vehicle,
    Worker,
    Workshop,
    WorkshopAvailabilityHistory,
    WorkshopAvailabilityState,
    WorkshopBranch,
    WorkshopOwner,
    WorkshopOwnerLink,
)
from app.api.v1.endpoints.auth import ensure_email_not_taken, ensure_permission_catalog, ensure_role_catalog
from app.schemas.emergency import IncidentListItem
from app.schemas.user import (
    BranchSummary,
    DailyMetricResponse,
    WorkshopAvailabilityUpdate,
    WorkshopCatalogSummary,
    WorkshopDashboardMetrics,
    WorkshopProfileResponse,
    WorkerCreateRequest,
    WorkerSummary,
    WorkshopOwnerSummary,
)

router = APIRouter()


def branch_to_summary(branch: WorkshopBranch) -> BranchSummary:
    return BranchSummary(
        id=branch.id,
        workshop_id=branch.workshop_id,
        name=branch.name,
        address=branch.address,
        coverage_radius_km=branch.coverage_radius_km,
        serves_24h=branch.serves_24h,
        max_concurrent_capacity=branch.max_concurrent_capacity,
        is_active=branch.is_active,
    )


def owner_to_summary(owner: WorkshopOwner | None) -> WorkshopOwnerSummary | None:
    if not owner:
        return None
    return WorkshopOwnerSummary(
        id=owner.id,
        account_id=owner.account_id,
        first_name=owner.first_name,
        last_name=owner.last_name,
        national_id=owner.national_id,
        email=owner.email,
        phone=owner.phone,
    )


def worker_to_summary(worker: Worker) -> WorkerSummary:
    return WorkerSummary(
        id=worker.id,
        account_id=worker.account_id,
        branch_id=worker.branch_id,
        first_name=worker.first_name,
        last_name=worker.last_name,
        national_id=worker.national_id,
        phone=worker.phone,
        email=worker.email,
        main_specialty=worker.main_specialty,
        operational_status=worker.operational_status.name if worker.operational_status else None,
        is_available=worker.is_available,
        current_latitude=worker.current_latitude,
        current_longitude=worker.current_longitude,
        last_location_at=worker.last_location_at,
        average_rating=worker.average_rating,
    )


def workshop_to_response(workshop: Workshop) -> WorkshopProfileResponse:
    return WorkshopProfileResponse(
        id=workshop.id,
        trade_name=workshop.trade_name,
        legal_name=workshop.legal_name,
        tax_id=workshop.tax_id,
        email=workshop.email,
        phone=workshop.phone,
        address=workshop.address,
        city=workshop.city,
        coverage_radius_km=workshop.coverage_radius_km,
        serves_24h=workshop.serves_24h,
        max_concurrent_capacity=workshop.max_concurrent_capacity,
        is_available=workshop.is_available,
        availability_state=workshop.availability_state.name if workshop.availability_state else None,
        current_concurrent_capacity=workshop.current_concurrent_capacity,
        accepts_requests=workshop.accepts_requests,
        is_admin_approved=workshop.is_admin_approved,
        approved_at=workshop.approved_at,
        approval_notes=workshop.approval_notes,
        average_rating=workshop.average_rating,
        total_ratings=workshop.total_ratings,
        primary_owner=owner_to_summary(workshop.primary_owner),
        branches=[branch_to_summary(branch) for branch in workshop.branches],
    )


async def assert_workshop_scope(current_user: Account, workshop_id: int, session: AsyncSession) -> Workshop:
    workshop = await session.scalar(
        select(Workshop)
        .options(
            selectinload(Workshop.branches),
            selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner).selectinload(WorkshopOwner.account),
            selectinload(Workshop.workers).selectinload(Worker.operational_status),
            selectinload(Workshop.availability_state),
        )
        .where(Workshop.id == workshop_id)
    )
    if not workshop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no encontrado.")
    if current_user.primary_role == AccountRoleName.WORKSHOP_OWNER.value:
        owner = await session.scalar(
            select(WorkshopOwner)
            .options(selectinload(WorkshopOwner.workshop_links))
            .where(WorkshopOwner.account_id == current_user.id)
        )
        if not owner or workshop_id not in {link.workshop_id for link in owner.workshop_links}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes acceder a otro taller.")
    if current_user.primary_role == AccountRoleName.WORKER.value:
        worker = await session.scalar(select(Worker).where(Worker.account_id == current_user.id))
        if not worker or worker.workshop_id != workshop_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes acceder a otro taller.")
    return workshop


@router.get("/{workshop_id}", response_model=WorkshopProfileResponse)
async def get_workshop_profile(
    workshop_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> WorkshopProfileResponse:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    return workshop_to_response(workshop)


@router.get("/{workshop_id}/branches", response_model=list[BranchSummary])
async def list_workshop_branches(
    workshop_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> list[BranchSummary]:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    return [branch_to_summary(branch) for branch in workshop.branches]


@router.patch("/{workshop_id}/availability", response_model=WorkshopProfileResponse)
async def update_workshop_availability(
    workshop_id: int,
    payload: WorkshopAvailabilityUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> WorkshopProfileResponse:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    workshop.is_available = payload.is_available
    workshop.max_concurrent_capacity = payload.max_concurrent_capacity
    if payload.current_concurrent_capacity is not None:
        workshop.current_concurrent_capacity = payload.current_concurrent_capacity
    if payload.accepts_requests is not None:
        workshop.accepts_requests = payload.accepts_requests
    state_name = payload.availability_state
    if not state_name:
        state_name = "disponible" if payload.is_available else "pausado"
    availability_state = await session.scalar(select(WorkshopAvailabilityState).where(WorkshopAvailabilityState.name == state_name))
    if availability_state:
        previous_state_id = workshop.availability_state_id
        workshop.availability_state_id = availability_state.id
        session.add(
            WorkshopAvailabilityHistory(
                workshop_id=workshop.id,
                old_state_id=previous_state_id,
                new_state_id=availability_state.id,
                current_capacity=workshop.current_concurrent_capacity,
                accepts_requests=workshop.accepts_requests,
                notes=payload.notes,
                action_account_id=current_user.id,
            )
        )
    if workshop.branches:
        workshop.branches[0].max_concurrent_capacity = payload.max_concurrent_capacity
    await session.commit()
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    return workshop_to_response(workshop)


@router.get("/{workshop_id}/requests", response_model=list[IncidentListItem])
async def list_workshop_requests(
    workshop_id: int,
    include_unassigned: bool = Query(default=True),
    status_name: str | None = Query(default=None, max_length=50),
    priority_name: str | None = Query(default=None, max_length=20),
    location: str | None = Query(default=None, max_length=120),
    search: str | None = Query(default=None, max_length=120),
    reported_from: date | None = Query(default=None),
    reported_to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> list[IncidentListItem]:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    statement = select(Incident)
    if include_unassigned:
        statement = statement.where(or_(Incident.assigned_workshop_id == workshop_id, Incident.assigned_workshop_id.is_(None)))
    else:
        statement = statement.where(Incident.assigned_workshop_id == workshop_id)
    if status_name:
        statement = statement.where(Incident.status.has(IncidentStatus.name == status_name.strip().lower()))
    if priority_name:
        statement = statement.where(Incident.priority.has(Priority.name == priority_name.strip().lower()))
    if reported_from:
        statement = statement.where(Incident.reported_at >= datetime.combine(reported_from, datetime.min.time()))
    if reported_to:
        statement = statement.where(Incident.reported_at <= datetime.combine(reported_to, datetime.max.time()))
    if location:
        location_pattern = f"%{location.strip()}%"
        statement = statement.where(
            or_(
                Incident.address_text.ilike(location_pattern),
                Incident.assigned_branch.has(WorkshopBranch.address.ilike(location_pattern)),
                Incident.assigned_branch.has(WorkshopBranch.name.ilike(location_pattern)),
                Incident.assigned_workshop.has(Workshop.city.ilike(location_pattern)),
            )
        )
    if search:
        search_pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Incident.address_text.ilike(search_pattern),
                Incident.client.has(User.first_name.ilike(search_pattern)),
                Incident.client.has(User.last_name.ilike(search_pattern)),
                Incident.vehicle.has(Vehicle.plate.ilike(search_pattern)),
                Incident.vehicle.has(Vehicle.brand.ilike(search_pattern)),
                Incident.vehicle.has(Vehicle.model.ilike(search_pattern)),
            )
        )
    incidents = (
        await session.scalars(
            statement.options(
                selectinload(Incident.client).selectinload(User.account),
                selectinload(Incident.vehicle),
                selectinload(Incident.status),
                selectinload(Incident.priority),
                selectinload(Incident.assigned_worker),
                selectinload(Incident.assigned_branch),
                selectinload(Incident.evidences),
                selectinload(Incident.final_incident_type),
                selectinload(Incident.manual_incident_type),
            ).order_by(Incident.reported_at.desc())
        )
    ).all()
    return [
        IncidentListItem(
            id=item.id,
            client_name=f"{item.client.first_name} {item.client.last_name}",
            client_phone=item.client.phone or "",
            vehicle_label=f"{item.vehicle.brand} {item.vehicle.model}",
            plate=item.vehicle.plate,
            branch_name=item.assigned_branch.name if item.assigned_branch else None,
            city=workshop.city,
            address_text=item.address_text,
            manual_incident_type=item.manual_incident_type_name,
            final_classification=item.final_classification,
            priority=item.priority.name,
            status=item.status.name,
            estimated_cost=item.estimated_cost,
            final_cost=item.final_cost,
            reported_at=item.reported_at,
            assigned_worker_name=f"{item.assigned_worker.first_name} {item.assigned_worker.last_name}" if item.assigned_worker else None,
            evidence_count=len(item.evidences),
        )
        for item in incidents
    ]


@router.get("/{workshop_id}/dashboard", response_model=WorkshopDashboardMetrics)
async def get_workshop_dashboard(
    workshop_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> WorkshopDashboardMetrics:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    active_statuses = ["asignado", "tecnico_asignado", "en_camino", "trabajando"]
    active_incidents = await session.scalar(
        select(func.count(Incident.id))
        .join(IncidentStatus, Incident.status_id == IncidentStatus.id)
        .where(Incident.assigned_workshop_id == workshop_id, IncidentStatus.name.in_(active_statuses))
    )
    pending_status = await session.scalar(select(IncidentStatus).where(IncidentStatus.name == "pendiente"))
    pending_incidents = await session.scalar(
        select(func.count(Incident.id)).where(Incident.assigned_workshop_id == workshop_id, Incident.status_id == pending_status.id)
    )
    completed_today = await session.scalar(
        select(func.count(Incident.id)).where(
            Incident.assigned_workshop_id == workshop_id,
            func.date(Incident.service_finished_at) == date.today(),
        )
    )
    active_workers = await session.scalar(select(func.count(Worker.id)).where(Worker.workshop_id == workshop_id, Worker.is_active.is_(True)))
    available_workers = await session.scalar(
        select(func.count(Worker.id)).where(Worker.workshop_id == workshop_id, Worker.is_active.is_(True), Worker.is_available.is_(True))
    )
    total_branches = await session.scalar(select(func.count(WorkshopBranch.id)).where(WorkshopBranch.workshop_id == workshop_id))
    recent_revenue = await session.scalar(
        select(func.coalesce(func.sum(Payment.total_amount), 0)).where(Payment.workshop_id == workshop_id)
    )
    total_assignments = max((active_incidents or 0) + (pending_incidents or 0), 1)
    return WorkshopDashboardMetrics(
        active_incidents=active_incidents or 0,
        pending_incidents=pending_incidents or 0,
        completed_today=completed_today or 0,
        active_workers=active_workers or 0,
        available_workers=available_workers or 0,
        total_branches=total_branches or 0,
        average_rating=workshop.average_rating,
        acceptance_rate=Decimal(str(round(((active_incidents or 0) / total_assignments) * 100, 2))),
        recent_revenue=Decimal(str(recent_revenue or 0)),
        availability_state=workshop.availability_state.name if workshop.availability_state else None,
        current_capacity=workshop.current_concurrent_capacity,
        accepts_requests=workshop.accepts_requests,
    )


@router.get("/{workshop_id}/catalog", response_model=WorkshopCatalogSummary)
async def get_workshop_catalog(
    workshop_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> WorkshopCatalogSummary:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)
    specialties = (await session.scalars(select(Specialty.name).order_by(Specialty.name))).all()
    cities = (await session.scalars(select(Workshop.city).distinct().order_by(Workshop.city))).all()
    return WorkshopCatalogSummary(
        specialties=list(specialties),
        workers=[worker_to_summary(worker) for worker in workshop.workers],
        branches=[branch_to_summary(branch) for branch in workshop.branches],
        cities=list(cities),
    )


@router.post("/{workshop_id}/workers", response_model=WorkerSummary, status_code=status.HTTP_201_CREATED)
async def create_workshop_worker(
    workshop_id: int,
    payload: WorkerCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> WorkerSummary:
    workshop = await assert_workshop_scope(current_user, workshop_id, session)

    await ensure_email_not_taken(session, payload.email)
    role_map = await ensure_role_catalog(session)
    await ensure_permission_catalog(session, role_map)

    existing_national_id = await session.scalar(select(Worker).where(Worker.national_id == payload.national_id))
    if existing_national_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El documento ya está registrado.")

    branch_id = payload.branch_id
    if branch_id is not None:
        branch = await session.scalar(
            select(WorkshopBranch).where(WorkshopBranch.id == branch_id, WorkshopBranch.workshop_id == workshop.id)
        )
        if not branch:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La sucursal no pertenece al taller.")

    account = Account(
        email=str(payload.email),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        is_verified=True,
    )
    session.add(account)
    await session.flush()
    session.add(AccountRole(account_id=account.id, role_id=role_map[AccountRoleName.WORKER.value].id))

    worker = Worker(
        workshop_id=workshop.id,
        branch_id=branch_id,
        account_id=account.id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        national_id=payload.national_id,
        phone=payload.phone,
        email=str(payload.email),
        main_specialty=payload.main_specialty,
        is_available=True,
        is_active=True,
        created_by=current_user.email,
    )
    session.add(worker)
    await session.commit()
    await session.refresh(worker)
    return worker_to_summary(worker)


@router.get("/metrics/daily", response_model=list[DailyMetricResponse])
async def list_daily_metrics(
    limit: int = Query(default=7, ge=1, le=30),
    session: AsyncSession = Depends(get_db_session),
    _current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> list[DailyMetricResponse]:
    metrics = (await session.scalars(select(DailyMetric).order_by(DailyMetric.metric_date.desc()).limit(limit))).all()
    return [DailyMetricResponse.model_validate(metric) for metric in metrics]

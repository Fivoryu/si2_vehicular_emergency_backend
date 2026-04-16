from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.models.emergency import Incident, IncidentStatus, NotificationRecipient, Payment
from app.models.user import Account, AccountRoleName, AuthSession, User, Worker, Workshop, WorkshopBranch
from app.schemas.user import (
    AdminDashboardMetrics,
    BranchSummary,
    ClientDashboardSummary,
    DashboardBootstrapResponse,
    VehicleResponse,
    WorkerDashboardResponse,
)

router = APIRouter()


def branch_summary(branch: WorkshopBranch | None) -> BranchSummary | None:
    if not branch:
        return None
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


@router.get("/me", response_model=DashboardBootstrapResponse)
async def get_my_dashboard(
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(
        require_roles(
            AccountRoleName.CLIENT,
            AccountRoleName.WORKSHOP_OWNER,
            AccountRoleName.WORKER,
            AccountRoleName.ADMIN,
        )
    ),
) -> DashboardBootstrapResponse:
    role = current_account.primary_role
    if role == AccountRoleName.CLIENT.value:
        client = await session.scalar(
            select(User)
            .options(
                selectinload(User.account),
                selectinload(User.vehicles),
                selectinload(User.incidents).selectinload(Incident.status),
                selectinload(User.incidents).selectinload(Incident.priority),
                selectinload(User.incidents).selectinload(Incident.vehicle),
                selectinload(User.payments).selectinload(Payment.payment_method),
                selectinload(User.payments).selectinload(Payment.status),
            )
            .where(User.account_id == current_account.id)
        )
        if not client:
            raise HTTPException(status_code=404, detail="Perfil de cliente no encontrado.")
        unread_notifications = await session.scalar(
            select(func.count(NotificationRecipient.id)).where(
                NotificationRecipient.account_id == current_account.id,
                NotificationRecipient.is_read.is_(False),
            )
        )
        return DashboardBootstrapResponse(
            role=role,
            profile_id=client.id,
            profile_type="client",
            display_name=current_account.display_name,
            permissions=current_account.permission_codes,
            client_dashboard=ClientDashboardSummary(
                client_id=client.id,
                account_id=current_account.id,
                full_name=f"{client.first_name} {client.last_name}",
                email=client.email,
                phone=client.phone,
                vehicles=[VehicleResponse.model_validate(vehicle) for vehicle in client.vehicles],
                incidents=[
                    {
                        "id": incident.id,
                        "vehicle_label": f"{incident.vehicle.brand} {incident.vehicle.model}",
                        "status": incident.status.name,
                        "priority": incident.priority.name,
                        "reported_at": incident.reported_at,
                        "address_text": incident.address_text,
                        "final_classification": incident.final_classification,
                        "eta_minutes": incident.eta_minutes,
                        "eta_at": incident.eta_at,
                    }
                    for incident in client.incidents
                ],
                payments=[
                    {
                        "id": payment.id,
                        "total_amount": payment.total_amount,
                        "status": payment.status.name,
                        "payment_method": payment.payment_method.name if payment.payment_method else None,
                        "requested_at": payment.requested_at,
                    }
                    for payment in client.payments
                ],
                unread_notifications=unread_notifications or 0,
                permissions=current_account.permission_codes,
            ),
        )

    if role == AccountRoleName.WORKER.value:
        worker = await session.scalar(
            select(Worker)
            .options(
                selectinload(Worker.workshop),
                selectinload(Worker.branch),
                selectinload(Worker.operational_status),
                selectinload(Worker.incidents).selectinload(Incident.client),
                selectinload(Worker.incidents).selectinload(Incident.vehicle),
                selectinload(Worker.incidents).selectinload(Incident.status),
                selectinload(Worker.incidents).selectinload(Incident.priority),
            )
            .where(Worker.account_id == current_account.id)
        )
        if not worker:
            raise HTTPException(status_code=404, detail="Perfil de trabajador no encontrado.")
        unread_notifications = await session.scalar(
            select(func.count(NotificationRecipient.id)).where(
                NotificationRecipient.account_id == current_account.id,
                NotificationRecipient.is_read.is_(False),
            )
        )
        return DashboardBootstrapResponse(
            role=role,
            profile_id=worker.id,
            profile_type="worker",
            workshop_id=worker.workshop_id,
            branch_id=worker.branch_id,
            display_name=current_account.display_name,
            permissions=current_account.permission_codes,
            worker_dashboard=WorkerDashboardResponse(
                worker_id=worker.id,
                account_id=worker.account_id,
                workshop_id=worker.workshop_id,
                workshop_name=worker.workshop.trade_name,
                branch=branch_summary(worker.branch),
                operational_status=worker.operational_status.name if worker.operational_status else None,
                is_available=worker.is_available,
                average_rating=worker.average_rating,
                assigned_incidents=[
                    {
                        "id": incident.id,
                        "client_name": f"{incident.client.first_name} {incident.client.last_name}",
                        "vehicle_label": f"{incident.vehicle.brand} {incident.vehicle.model}",
                        "status": incident.status.name,
                        "priority": incident.priority.name,
                        "address_text": incident.address_text,
                        "eta_minutes": incident.eta_minutes,
                    }
                    for incident in worker.incidents
                ],
                unread_notifications=unread_notifications or 0,
                permissions=current_account.permission_codes,
            ),
        )

    if role == AccountRoleName.ADMIN.value:
        total_accounts = await session.scalar(select(func.count(Account.id)))
        total_clients = await session.scalar(select(func.count(User.id)))
        total_workshops = await session.scalar(select(func.count(Workshop.id)))
        total_branches = await session.scalar(select(func.count(WorkshopBranch.id)))
        total_workers = await session.scalar(select(func.count(Worker.id)))
        total_incidents = await session.scalar(select(func.count(Incident.id)))
        active_incidents = await session.scalar(
            select(func.count(Incident.id))
            .join(IncidentStatus, Incident.status_id == IncidentStatus.id)
            .where(IncidentStatus.name.in_(["asignado", "tecnico_asignado", "en_camino", "trabajando"]))
        )
        pending_incidents = await session.scalar(
            select(func.count(Incident.id))
            .join(IncidentStatus, Incident.status_id == IncidentStatus.id)
            .where(IncidentStatus.name == "pendiente")
        )
        active_sessions = await session.scalar(
            select(func.count(AuthSession.id)).where(AuthSession.is_revoked.is_(False), AuthSession.logged_out_at.is_(None))
        )
        platform_revenue = await session.scalar(select(func.coalesce(func.sum(Payment.platform_fee), 0)))
        recent_incidents = (
            await session.scalars(
                select(Incident)
                .options(
                    selectinload(Incident.client),
                    selectinload(Incident.vehicle),
                    selectinload(Incident.status),
                )
                .order_by(Incident.reported_at.desc())
                .limit(8)
            )
        ).all()
        workshops = (
            await session.scalars(
                select(Workshop)
                .options(selectinload(Workshop.branches), selectinload(Workshop.availability_state))
                .order_by(Workshop.trade_name)
            )
        ).all()
        return DashboardBootstrapResponse(
            role=role,
            profile_id=current_account.admin_profile.id if current_account.admin_profile else None,
            profile_type="admin",
            display_name=current_account.display_name,
            permissions=current_account.permission_codes,
            admin_dashboard=AdminDashboardMetrics(
                total_accounts=total_accounts or 0,
                total_clients=total_clients or 0,
                total_workshops=total_workshops or 0,
                total_branches=total_branches or 0,
                total_workers=total_workers or 0,
                total_incidents=total_incidents or 0,
                active_incidents=active_incidents or 0,
                pending_incidents=pending_incidents or 0,
                platform_revenue=Decimal(str(platform_revenue or 0)),
                active_sessions=active_sessions or 0,
                workshops=[
                    {
                        "id": workshop.id,
                        "trade_name": workshop.trade_name,
                        "city": workshop.city,
                        "branches": len(workshop.branches),
                        "rating": workshop.average_rating,
                        "is_available": workshop.is_available,
                        "availability_state": workshop.availability_state.name if workshop.availability_state else None,
                        "is_admin_approved": workshop.is_admin_approved,
                    }
                    for workshop in workshops
                ],
                recent_incidents=[
                    {
                        "id": incident.id,
                        "client_name": f"{incident.client.first_name} {incident.client.last_name}",
                        "vehicle_label": f"{incident.vehicle.brand} {incident.vehicle.model}",
                        "status": incident.status.name,
                        "reported_at": incident.reported_at,
                        "eta_minutes": incident.eta_minutes,
                    }
                    for incident in recent_incidents
                ],
            ),
        )

    return DashboardBootstrapResponse(
        role=role or "",
        profile_id=current_account.owner_profile.id if current_account.owner_profile else None,
        profile_type="workshop_owner",
        display_name=current_account.display_name,
        permissions=current_account.permission_codes,
    )

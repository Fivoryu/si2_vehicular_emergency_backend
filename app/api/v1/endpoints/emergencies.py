from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.models.emergency import (
    AIInference,
    Assignment,
    Evidence,
    Incident,
    IncidentType,
    IncidentStatus,
    IncidentStatusHistory,
    Notification,
    Payment,
    Priority,
    WorkerAssignmentHistory,
)
from app.models.user import Account, AccountRoleName, User, Vehicle, Worker, Workshop, WorkshopBranch
from app.schemas.emergency import (
    EmergencyCreate,
    EmergencyDecision,
    EmergencyStatusUpdate,
    IncidentDetailResponse,
    IncidentListItem,
    EvidenceCreate,
    EvidenceResponse,
)

router = APIRouter()


async def get_priority_by_name(session: AsyncSession, name: str) -> Priority:
    priority = await session.scalar(select(Priority).where(Priority.name == name))
    if not priority:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prioridad no encontrada.")
    return priority


async def get_status_by_name(session: AsyncSession, name: str) -> IncidentStatus:
    status_row = await session.scalar(select(IncidentStatus).where(IncidentStatus.name == name))
    if not status_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estado no encontrado.")
    return status_row


async def get_incident_type_by_name(session: AsyncSession, name: str | None) -> IncidentType | None:
    if not name:
        return None
    normalized = name.strip().lower()
    incident_type = await session.scalar(select(IncidentType).where(IncidentType.name == normalized))
    if incident_type:
        return incident_type
    fallback = IncidentType(name=normalized, description=f"Tipo generado para {normalized}", is_active=True)
    session.add(fallback)
    await session.flush()
    return fallback


def serialize_incident_list_item(item: Incident, fallback_city: str | None = None) -> IncidentListItem:
    return IncidentListItem(
        id=item.id,
        client_name=f"{item.client.first_name} {item.client.last_name}",
        client_phone=item.client.phone or "",
        vehicle_label=f"{item.vehicle.brand} {item.vehicle.model}",
        plate=item.vehicle.plate,
        branch_name=item.assigned_branch.name if item.assigned_branch else None,
        city=item.assigned_workshop.city if item.assigned_workshop else fallback_city,
        address_text=item.address_text,
        manual_incident_type=item.manual_incident_type_name,
        final_classification=item.final_classification,
        priority=item.priority.name,
        status=item.status.name,
        estimated_cost=item.estimated_cost,
        final_cost=item.final_cost,
        eta_minutes=item.eta_minutes,
        workshop_distance_km=item.workshop_distance_km,
        reported_at=item.reported_at,
        assigned_worker_name=f"{item.assigned_worker.first_name} {item.assigned_worker.last_name}" if item.assigned_worker else None,
        evidence_count=len(item.evidences),
    )


@router.post("", response_model=IncidentDetailResponse, status_code=status.HTTP_201_CREATED)
async def report_emergency(
    payload: EmergencyCreate,
    session: AsyncSession = Depends(get_db_session),
) -> IncidentDetailResponse:
    client = await session.get(User, payload.client_id)
    vehicle = await session.get(Vehicle, payload.vehicle_id)
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado.")
    if not vehicle or vehicle.owner_id != payload.client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehículo no encontrado para el cliente.")
    pending_status = await get_status_by_name(session, "pendiente")
    priority = await get_priority_by_name(session, payload.priority_name)

    manual_incident_type = await get_incident_type_by_name(session, payload.manual_incident_type)
    incident = Incident(
        client_id=payload.client_id,
        vehicle_id=payload.vehicle_id,
        status_id=pending_status.id,
        priority_id=priority.id,
        manual_incident_type_id=manual_incident_type.id if manual_incident_type else None,
        final_incident_type_id=manual_incident_type.id if manual_incident_type else None,
        incident_latitude=payload.incident_latitude,
        incident_longitude=payload.incident_longitude,
        address_text=payload.address_text,
        description_text=payload.description_text,
    )
    session.add(incident)
    await session.commit()
    return await get_incident_detail(incident.id, session)


@router.post("/{incident_id}/evidences", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def add_evidence(
    incident_id: int,
    payload: EvidenceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceResponse:
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    evidence = Evidence(
        incident_id=incident_id,
        evidence_type=payload.evidence_type,
        resource_url=payload.resource_url,
        audio_transcription=payload.audio_transcription,
        ai_analysis=payload.ai_analysis,
        visual_order=payload.visual_order,
    )
    session.add(evidence)
    await session.commit()
    await session.refresh(evidence)
    return EvidenceResponse.model_validate(evidence)


@router.get("", response_model=list[IncidentListItem])
async def list_incidents(
    session: AsyncSession = Depends(get_db_session),
    _current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> list[IncidentListItem]:
    incidents = (
        await session.scalars(
            select(Incident)
            .options(
                selectinload(Incident.client).selectinload(User.account),
                selectinload(Incident.vehicle),
                selectinload(Incident.status),
                selectinload(Incident.priority),
                selectinload(Incident.assigned_worker),
                selectinload(Incident.assigned_workshop),
                selectinload(Incident.assigned_branch),
                selectinload(Incident.evidences),
                selectinload(Incident.manual_incident_type),
                selectinload(Incident.final_incident_type),
            )
            .order_by(Incident.reported_at.desc())
        )
    ).all()
    return [serialize_incident_list_item(item) for item in incidents]


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident_detail(
    incident_id: int,
    session: AsyncSession = Depends(get_db_session),
    _current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER, AccountRoleName.CLIENT)),
) -> IncidentDetailResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.vehicle),
            selectinload(Incident.assigned_workshop),
            selectinload(Incident.assigned_worker),
            selectinload(Incident.assigned_branch),
            selectinload(Incident.status),
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.ai_incident_type),
            selectinload(Incident.final_incident_type),
            selectinload(Incident.evidences),
            selectinload(Incident.assignments).selectinload(Assignment.candidate_workshop),
            selectinload(Incident.worker_assignments).selectinload(WorkerAssignmentHistory.worker),
            selectinload(Incident.worker_assignments).selectinload(WorkerAssignmentHistory.branch),
            selectinload(Incident.history).selectinload(IncidentStatusHistory.new_status),
            selectinload(Incident.payments).selectinload(Payment.status),
            selectinload(Incident.payments).selectinload(Payment.payment_method),
            selectinload(Incident.notifications).selectinload(Notification.recipients),
            selectinload(Incident.ai_inferences),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    payment = incident.payments[0] if incident.payments else None
    return IncidentDetailResponse(
        id=incident.id,
        client_name=f"{incident.client.first_name} {incident.client.last_name}",
        client_phone=incident.client.phone,
        vehicle={
            "id": incident.vehicle.id,
            "plate": incident.vehicle.plate,
            "brand": incident.vehicle.brand,
            "model": incident.vehicle.model,
            "year": incident.vehicle.year,
            "color": incident.vehicle.color,
            "type": incident.vehicle.vehicle_type.value if incident.vehicle.vehicle_type else None,
        },
        workshop=(
            {
                "id": incident.assigned_workshop.id,
                "trade_name": incident.assigned_workshop.trade_name,
                "city": incident.assigned_workshop.city,
                "phone": incident.assigned_workshop.phone,
                "rating": incident.assigned_workshop.average_rating,
            }
            if incident.assigned_workshop
            else None
        ),
        worker=(
            {
                "id": incident.assigned_worker.id,
                "name": f"{incident.assigned_worker.first_name} {incident.assigned_worker.last_name}",
                "phone": incident.assigned_worker.phone,
                "specialty": incident.assigned_worker.main_specialty,
            }
            if incident.assigned_worker
            else None
        ),
        branch=(
            {
                "id": incident.assigned_branch.id,
                "name": incident.assigned_branch.name,
                "address": incident.assigned_branch.address,
            }
            if incident.assigned_branch
            else None
        ),
        status=incident.status.name,
        priority=incident.priority.name,
        description_text=incident.description_text,
        address_text=incident.address_text,
        coordinates={"lat": incident.incident_latitude, "lng": incident.incident_longitude},
        manual_incident_type=incident.manual_incident_type_name,
        ai_incident_type=incident.ai_incident_type_name,
        ai_confidence=incident.ai_confidence,
        final_classification=incident.final_classification,
        estimated_cost=incident.estimated_cost,
        final_cost=incident.final_cost,
        eta_minutes=incident.eta_minutes,
        eta_at=incident.eta_at,
        eta_last_calculated_at=incident.eta_last_calculated_at,
        workshop_distance_km=incident.workshop_distance_km,
        payment_status=payment.status.name if payment else None,
        payment_method=payment.payment_method.name if payment and payment.payment_method else None,
        payment_summary=(
            {
                "total_amount": payment.total_amount,
                "platform_fee": payment.platform_fee,
                "workshop_amount": payment.workshop_amount,
                "method": payment.payment_method.name if payment.payment_method else None,
            }
            if payment
            else None
        ),
        evidences=[EvidenceResponse.model_validate(item) for item in incident.evidences],
        history=[
            {
                "id": item.id,
                "new_status": item.new_status.name,
                "action_account_id": item.action_account_id,
                "notes": item.notes,
                "changed_at": item.changed_at,
            }
            for item in incident.history
        ],
        assignments=[
            {
                "id": item.id,
                "workshop_name": item.candidate_workshop.trade_name,
                "score": item.assignment_score,
                "selected": item.was_selected,
                "rejected": item.was_rejected,
                "rejection_reason": item.rejection_reason,
            }
            for item in incident.assignments
        ],
        worker_assignment_history=[
            {
                "id": item.id,
                "worker_name": f"{item.worker.first_name} {item.worker.last_name}",
                "branch_name": item.branch.name if item.branch else None,
                "assigned_at": item.assigned_at,
                "unassigned_at": item.unassigned_at,
                "is_current": item.is_current,
                "reason": item.reason,
            }
            for item in incident.worker_assignments
        ],
        notifications=[
            {
                "id": item.id,
                "type": item.notification_type,
                "title": item.title,
                "message": item.message,
                "sent_at": item.sent_at,
                "recipients": [
                    {
                        "account_id": recipient.account_id,
                        "is_read": recipient.is_read,
                    }
                    for recipient in item.recipients
                ],
            }
            for item in incident.notifications
        ],
        ai_inferences=[
            {
                "id": item.id,
                "process_type": item.process_type,
                "model_provider": item.model_provider,
                "model_version": item.model_version,
                "output_summary": item.output_summary,
                "confidence": item.confidence,
                "processed_at": item.processed_at,
                "is_final_result": item.is_final_result,
            }
            for item in incident.ai_inferences
        ],
    )


@router.patch("/{incident_id}/decision", response_model=IncidentDetailResponse)
async def decide_emergency(
    incident_id: int,
    payload: EmergencyDecision,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> IncidentDetailResponse:
    incident = await session.get(Incident, incident_id)
    workshop = await session.get(Workshop, payload.workshop_id)
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if not workshop or not workshop.is_available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no disponible.")
    status_name = "asignado" if payload.accepted else "rechazado"
    new_status = await get_status_by_name(session, status_name)
    old_status_id = incident.status_id
    primary_branch = await session.scalar(select(WorkshopBranch).where(WorkshopBranch.workshop_id == workshop.id).order_by(WorkshopBranch.id))
    assignment = Assignment(
        incident_id=incident.id,
        candidate_workshop_id=workshop.id,
        assignment_score=Decimal("92.50") if payload.accepted else Decimal("45.00"),
        used_criteria={"distance": 35, "capacity": 25, "rating": 20, "availability": 20},
        was_selected=payload.accepted,
        was_rejected=not payload.accepted,
        rejected_at=datetime.utcnow() if not payload.accepted else None,
        rejection_reason=payload.rejection_reason,
    )
    session.add(assignment)
    incident.assigned_workshop_id = workshop.id
    incident.assigned_branch_id = primary_branch.id if primary_branch and payload.accepted else None
    incident.status_id = new_status.id
    incident.assigned_at = datetime.utcnow()
    if payload.accepted:
        incident.accepted_at = datetime.utcnow()
        incident.eta_minutes = 25
        incident.eta_at = datetime.utcnow()
        incident.eta_last_calculated_at = datetime.utcnow()
        incident.workshop_distance_km = Decimal("8.50")
        session.add(
            AIInference(
                incident_id=incident.id,
                process_type="asignacion",
                model_provider="rule-engine",
                model_version="v1",
                input_summary="Asignacion por disponibilidad y cobertura",
                output_summary=f"Taller {workshop.trade_name} seleccionado con ETA 25 minutos.",
                confidence=Decimal("92.50"),
                duration_ms=180,
                is_final_result=True,
            )
        )
    session.add(
        IncidentStatusHistory(
            incident_id=incident.id,
            old_status_id=old_status_id,
            new_status_id=new_status.id,
            action_account_id=current_user.id,
            notes="Solicitud aceptada" if payload.accepted else payload.rejection_reason,
        )
    )
    await session.commit()
    return await get_incident_detail(incident.id, session)


@router.patch("/{incident_id}/status", response_model=IncidentDetailResponse)
async def update_emergency_status(
    incident_id: int,
    payload: EmergencyStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN, AccountRoleName.WORKER)),
) -> IncidentDetailResponse:
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    new_status = await get_status_by_name(session, payload.status_name)
    old_status_id = incident.status_id
    incident.status_id = new_status.id
    if payload.worker_id:
        worker = await session.get(Worker, payload.worker_id)
        if worker:
            current_assignments = (
                await session.scalars(
                    select(WorkerAssignmentHistory).where(
                        WorkerAssignmentHistory.incident_id == incident.id,
                        WorkerAssignmentHistory.is_current.is_(True),
                    )
                )
            ).all()
            for assignment in current_assignments:
                assignment.is_current = False
                assignment.unassigned_at = datetime.utcnow()
            incident.assigned_branch_id = worker.branch_id
            incident.assigned_worker_id = worker.id
            session.add(
                WorkerAssignmentHistory(
                    incident_id=incident.id,
                    worker_id=worker.id,
                    branch_id=worker.branch_id,
                    is_current=True,
                    action_account_id=current_user.id,
                    reason=payload.notes,
                )
            )
    if payload.status_name == "en_camino":
        incident.accepted_at = incident.accepted_at or datetime.utcnow()
        incident.eta_minutes = incident.eta_minutes or 20
        incident.eta_last_calculated_at = datetime.utcnow()
    if payload.status_name == "trabajando":
        incident.service_started_at = datetime.utcnow()
        incident.eta_minutes = 0
    if payload.status_name == "finalizado":
        incident.service_finished_at = datetime.utcnow()
    session.add(
        IncidentStatusHistory(
            incident_id=incident.id,
            old_status_id=old_status_id,
            new_status_id=new_status.id,
            action_account_id=current_user.id,
            notes=payload.notes,
        )
    )
    await session.commit()
    return await get_incident_detail(incident.id, session)

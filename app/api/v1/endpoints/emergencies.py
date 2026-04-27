from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, require_roles
from app.models.emergency import (
    AIInference,
    Assignment,
    Evidence,
    Incident,
    IncidentChatMessage,
    IncidentType,
    IncidentStatus,
    IncidentStatusHistory,
    Notification,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Priority,
    WorkerAssignmentHistory,
    WorkerRating,
    WorkshopRating,
)
from app.models.user import Account, AccountRoleName, User, Vehicle, Worker, WorkerStatus, WorkerStatusHistory, Workshop, WorkshopBranch, WorkshopOwnerLink
from app.schemas.emergency import (
    AIProcessResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    EmergencyCreate,
    EmergencyDecision,
    EmergencyStatusUpdate,
    IncidentDetailResponse,
    IncidentListItem,
    ServiceRatingCreate,
    ServiceRatingResponse,
    PaymentCreate,
    PaymentResponse,
    TechnicianOfferItem,
    TechnicianSelect,
    TrackingResponse,
    WorkerLocationUpdate,
    EvidenceCreate,
    EvidenceResponse,
)
from app.services.incident_ai import MODEL_PROVIDER as LOCAL_AI_PROVIDER
from app.services.incident_ai import MODEL_VERSION as LOCAL_AI_VERSION
from app.services.incident_ai import analyze_incident, rank_assignment_candidates
from app.services.notification_dispatcher import create_notification
from app.services.trained_vision_ai import analyze_image_evidence

router = APIRouter()


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_distance_km(
    origin_latitude: Decimal | None,
    origin_longitude: Decimal | None,
    destination_latitude: Decimal | None,
    destination_longitude: Decimal | None,
) -> Decimal | None:
    if None in {origin_latitude, origin_longitude, destination_latitude, destination_longitude}:
        return None
    lat1 = radians(float(origin_latitude))
    lon1 = radians(float(origin_longitude))
    lat2 = radians(float(destination_latitude))
    lon2 = radians(float(destination_longitude))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    distance = 6371 * 2 * asin(sqrt(value))
    return Decimal(str(round(distance, 2)))


def calculate_service_cost(
    *,
    incident: Incident,
    distance_km: Decimal | None,
    status_name: str | None = None,
) -> dict[str, Decimal]:
    priority_multiplier = {
        "alta": Decimal("1.35"),
        "media": Decimal("1.15"),
        "baja": Decimal("1.00"),
    }.get(incident.priority.name if incident.priority else "media", Decimal("1.10"))
    type_base = {
        "bateria": Decimal("90.00"),
        "llanta": Decimal("85.00"),
        "motor": Decimal("150.00"),
        "choque": Decimal("180.00"),
        "electrico": Decimal("125.00"),
        "cerradura": Decimal("75.00"),
        "remolque": Decimal("220.00"),
    }.get(incident.final_classification or incident.manual_incident_type_name or "otro", Decimal("110.00"))
    distance_component = money((distance_km or Decimal("5.00")) * Decimal("4.50"))
    demand_component = money(priority_multiplier * Decimal("28.00"))
    operating_component = Decimal("45.00")
    subtotal = money(type_base + distance_component + demand_component + operating_component)
    platform_component = money(subtotal * Decimal("0.10"))
    final_total = money(subtotal + platform_component)
    if status_name != "finalizado":
        final_total = money(final_total * Decimal("0.95"))
    return {
        "base_service": type_base,
        "distance": distance_component,
        "demand": demand_component,
        "operating": operating_component,
        "platform_fee": platform_component,
        "total": final_total,
    }


def calculate_client_suggested_price(
    *,
    incident_type_name: str | None,
    priority_name: str,
    offered_price: Decimal | None = None,
) -> Decimal:
    type_base = {
        "bateria": Decimal("90.00"),
        "llanta": Decimal("85.00"),
        "motor": Decimal("150.00"),
        "choque": Decimal("180.00"),
        "electrico": Decimal("125.00"),
        "cerradura": Decimal("75.00"),
        "remolque": Decimal("220.00"),
        "accidente de tránsito": Decimal("180.00"),
        "daño mecánico": Decimal("145.00"),
        "asistencia vial": Decimal("95.00"),
        "robo": Decimal("160.00"),
    }.get((incident_type_name or "otro").strip().lower(), Decimal("110.00"))
    priority_extra = {"alta": Decimal("55.00"), "media": Decimal("30.00"), "baja": Decimal("15.00")}.get(
        priority_name.strip().lower(),
        Decimal("30.00"),
    )
    suggested = money(type_base + priority_extra + Decimal("35.00"))
    if offered_price and offered_price > 0:
        return money((suggested + offered_price) / Decimal("2"))
    return suggested


async def set_worker_operational_status(
    *,
    session: AsyncSession,
    worker: Worker | None,
    status_name: str,
    current_user: Account,
    notes: str | None = None,
) -> None:
    if not worker:
        return
    worker_status = await session.scalar(select(WorkerStatus).where(WorkerStatus.name == status_name))
    if not worker_status:
        return
    old_status_id = worker.operational_status_id
    if old_status_id == worker_status.id:
        return
    worker.operational_status_id = worker_status.id
    worker.is_available = status_name == "libre"
    worker.updated_at = datetime.utcnow()
    worker.updated_by = current_user.email
    session.add(
        WorkerStatusHistory(
            worker_id=worker.id,
            old_status_id=old_status_id,
            new_status_id=worker_status.id,
            notes=notes,
            action_account_id=current_user.id,
        )
    )


def worker_status_from_incident_status(status_name: str) -> str | None:
    return {
        "tecnico_asignado": "en_camino",
        "en_camino": "en_camino",
        "trabajando": "en_servicio",
        "finalizado": "libre",
        "rechazado": "libre",
    }.get(status_name)


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


async def apply_local_ai_processing(
    *,
    session: AsyncSession,
    incident: Incident,
    requested_priority_name: str | None = None,
) -> tuple[Incident, object]:
    analysis = analyze_incident(
        description_text=incident.description_text,
        address_text=incident.address_text,
        manual_incident_type=incident.manual_incident_type_name,
        evidences=incident.evidences,
        requested_priority=requested_priority_name or (incident.priority.name if incident.priority else None),
    )
    ai_type = await get_incident_type_by_name(session, analysis.incident_type)
    priority = await get_priority_by_name(session, analysis.suggested_priority)
    incident.ai_incident_type_id = ai_type.id if ai_type else None
    incident.final_incident_type_id = ai_type.id if ai_type else incident.manual_incident_type_id
    incident.priority_id = priority.id
    incident.ai_confidence = analysis.confidence
    incident.updated_at = datetime.utcnow()
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="clasificacion",
            model_provider=LOCAL_AI_PROVIDER,
            model_version=LOCAL_AI_VERSION,
            input_summary=(
                f"Texto='{incident.description_text or ''}'. Direccion='{incident.address_text or ''}'. "
                f"Tipo manual='{incident.manual_incident_type_name or 'sin tipo'}'."
            ),
            output_summary=(
                f"CU19: tipo '{analysis.incident_type}' con confianza {analysis.confidence}%. "
                f"{analysis.summary}"
            ),
            confidence=analysis.confidence,
            duration_ms=120,
            is_final_result=True,
        )
    )
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="priorizacion",
            model_provider=LOCAL_AI_PROVIDER,
            model_version=LOCAL_AI_VERSION,
            input_summary=str(analysis.criteria),
            output_summary=(
                f"CU20: prioridad sugerida '{analysis.suggested_priority}' por señales "
                f"{', '.join(analysis.risk_signals) if analysis.risk_signals else 'operativas normales'}."
            ),
            confidence=analysis.confidence,
            duration_ms=85,
            is_final_result=True,
        )
    )
    return incident, analysis


async def build_ai_assignment_candidates(
    *,
    session: AsyncSession,
    incident: Incident,
    required_specialty: str,
    limit: int = 5,
):
    workshops = (
        await session.scalars(
            select(Workshop)
            .options(
                selectinload(Workshop.branches),
                selectinload(Workshop.workers).selectinload(Worker.operational_status),
            )
            .where(Workshop.is_active.is_(True), Workshop.is_available.is_(True))
        )
    ).unique().all()
    return rank_assignment_candidates(
        incident_latitude=incident.incident_latitude,
        incident_longitude=incident.incident_longitude,
        required_specialty=required_specialty,
        workshops=workshops,
        limit=limit,
    )


def add_assignment_rankings(
    *,
    session: AsyncSession,
    incident: Incident,
    candidates,
    selected_workshop_id: int | None = None,
) -> None:
    for candidate in candidates:
        session.add(
            Assignment(
                incident_id=incident.id,
                candidate_workshop_id=candidate.workshop_id,
                assignment_score=candidate.score,
                used_criteria=candidate.criteria,
                was_selected=selected_workshop_id == candidate.workshop_id,
            )
        )


def serialize_chat_message(message: IncidentChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        incident_id=message.incident_id,
        sender_account_id=message.sender_account_id,
        sender_role=message.sender_role,
        sender_name=message.sender_name,
        message_text=message.message_text,
        sent_at=message.sent_at,
    )


def can_access_incident_chat_or_tracking(incident: Incident, current_account: Account) -> bool:
    if current_account.primary_role == AccountRoleName.ADMIN.value:
        return True
    if incident.client.account_id == current_account.id:
        return True
    if incident.assigned_workshop and any(
        link.owner.account_id == current_account.id for link in incident.assigned_workshop.owner_links
    ):
        return True
    if incident.assigned_worker and incident.assigned_worker.account_id == current_account.id:
        return True
    return False


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
    incident.manual_incident_type = manual_incident_type
    incident.priority = priority
    session.add(incident)
    await session.flush()
    incident, ai_analysis = await apply_local_ai_processing(
        session=session,
        incident=incident,
        requested_priority_name=payload.priority_name,
    )
    suggested_price = calculate_client_suggested_price(
        incident_type_name=ai_analysis.incident_type,
        priority_name=ai_analysis.suggested_priority,
        offered_price=payload.offered_price,
    )
    incident.estimated_cost = payload.offered_price or suggested_price
    candidates = await build_ai_assignment_candidates(
        session=session,
        incident=incident,
        required_specialty=ai_analysis.required_specialty,
    )
    selected_candidate = candidates[0] if candidates else None
    if selected_candidate:
        assigned_status = await get_status_by_name(session, "asignado")
        incident.status_id = assigned_status.id
        incident.assigned_workshop_id = selected_candidate.workshop_id
        incident.assigned_branch_id = selected_candidate.branch_id
        incident.assigned_at = datetime.utcnow()
        incident.workshop_distance_km = selected_candidate.distance_km
        incident.eta_minutes = selected_candidate.eta_minutes
        incident.eta_at = datetime.utcnow() + timedelta(minutes=selected_candidate.eta_minutes or 20)
        incident.eta_last_calculated_at = datetime.utcnow()
        session.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                old_status_id=pending_status.id,
                new_status_id=assigned_status.id,
                notes="CU21 asignacion inteligente automatica",
            )
        )
    add_assignment_rankings(
        session=session,
        incident=incident,
        candidates=candidates,
        selected_workshop_id=selected_candidate.workshop_id if selected_candidate else None,
    )
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="asignacion",
            model_provider=LOCAL_AI_PROVIDER,
            model_version=LOCAL_AI_VERSION,
            input_summary=f"Especialidad requerida: {ai_analysis.required_specialty}. Candidatos evaluados: {len(candidates)}.",
            output_summary=(
                f"CU21: {'seleccionado ' + selected_candidate.workshop_name if selected_candidate else 'sin taller candidato disponible'} "
                f"con score {selected_candidate.score if selected_candidate else 'N/A'}."
            ),
            confidence=selected_candidate.score if selected_candidate else Decimal("45.00"),
            duration_ms=160,
            is_final_result=selected_candidate is not None,
        )
    )
    await create_notification(
        session=session,
        account_ids=[client.account_id],
        title="Emergencia reportada",
        message=(
            f"Tu solicitud fue registrada y asignada a {selected_candidate.workshop_name}."
            if selected_candidate
            else "Tu solicitud fue registrada correctamente y está pendiente de asignación."
        ),
        notification_type="emergencia_reportada",
        incident_id=incident.id,
    )
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="precio_sugerido",
            model_provider="rule-engine",
            model_version="v2",
            input_summary=f"Tipo {payload.manual_incident_type or 'otro'}, prioridad {priority.name}, oferta cliente {payload.offered_price}",
            output_summary=f"Precio sugerido Bs. {suggested_price}. Precio publicado Bs. {incident.estimated_cost}.",
            confidence=Decimal("88.00"),
            duration_ms=60,
            is_final_result=True,
        )
    )
    await session.commit()
    return await get_incident_detail(incident.id, session)


@router.post("/{incident_id}/evidences", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def add_evidence(
    incident_id: int,
    payload: EvidenceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    vision_result = analyze_image_evidence(payload.resource_url, payload.evidence_type)
    evidence = Evidence(
        incident_id=incident_id,
        evidence_type=payload.evidence_type,
        resource_url=payload.resource_url,
        audio_transcription=payload.audio_transcription,
        ai_analysis=payload.ai_analysis or (vision_result.as_evidence_analysis() if vision_result else None),
        visual_order=payload.visual_order,
    )
    session.add(evidence)
    await session.flush()
    if vision_result:
        session.add(
            AIInference(
                incident_id=incident.id,
                process_type="vision_imagen",
                model_provider=vision_result.provider,
                model_version=vision_result.model_version,
                input_summary=f"Evidencia {evidence.evidence_type}: {evidence.resource_url}",
                output_summary=vision_result.as_evidence_analysis(),
                confidence=vision_result.confidence,
                duration_ms=140,
                is_final_result=vision_result.used_trained_model,
            )
        )
        await apply_local_ai_processing(
            session=session,
            incident=incident,
            requested_priority_name=incident.priority.name if incident.priority else None,
        )
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


@router.get("/worker/available", response_model=list[IncidentListItem])
async def list_available_worker_incidents(
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKER)),
) -> list[IncidentListItem]:
    worker = await session.scalar(
        select(Worker)
        .options(selectinload(Worker.operational_status))
        .where(Worker.account_id == current_user.id)
    )
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trabajador no encontrado.")

    if not worker.is_available or (worker.operational_status and worker.operational_status.name != "libre"):
        return []

    candidate_statuses = ["pendiente", "asignado"]
    incidents = (
        await session.scalars(
            select(Incident)
            .join(IncidentStatus, Incident.status_id == IncidentStatus.id)
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
            .where(
                IncidentStatus.name.in_(candidate_statuses),
                Incident.assigned_worker_id.is_(None),
                or_(Incident.assigned_workshop_id == worker.workshop_id, Incident.assigned_workshop_id.is_(None)),
            )
            .order_by(Incident.reported_at.desc())
            .limit(10)
        )
    ).all()
    return [serialize_incident_list_item(item) for item in incidents]


@router.get("/{incident_id}/technician-offers", response_model=list[TechnicianOfferItem])
async def list_technician_offers(
    incident_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.CLIENT, AccountRoleName.ADMIN)),
) -> list[TechnicianOfferItem]:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
            selectinload(Incident.evidences),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if current_user.primary_role == AccountRoleName.CLIENT.value and incident.client.account_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes ver ofertas de este incidente.")

    analysis = analyze_incident(
        description_text=incident.description_text,
        address_text=incident.address_text,
        manual_incident_type=incident.final_classification or incident.manual_incident_type_name,
        evidences=incident.evidences,
        requested_priority=incident.priority.name,
    )
    candidates = await build_ai_assignment_candidates(
        session=session,
        incident=incident,
        required_specialty=analysis.required_specialty,
        limit=8,
    )
    candidate_worker_ids = [candidate.worker_id for candidate in candidates if candidate.worker_id]
    workers_query = (
        select(Worker)
        .options(selectinload(Worker.operational_status), selectinload(Worker.branch), selectinload(Worker.workshop))
        .where(Worker.is_active.is_(True), Worker.is_available.is_(True))
        .order_by(Worker.average_rating.desc(), Worker.id.asc())
        .limit(8)
    )
    if candidate_worker_ids:
        workers_query = (
            select(Worker)
            .options(selectinload(Worker.operational_status), selectinload(Worker.branch), selectinload(Worker.workshop))
            .where(Worker.id.in_(candidate_worker_ids))
        )
    workers = (await session.scalars(workers_query)).all()
    worker_by_id = {worker.id: worker for worker in workers}
    ordered_workers = [worker_by_id[worker_id] for worker_id in candidate_worker_ids if worker_id in worker_by_id] or workers
    offers: list[TechnicianOfferItem] = []
    for worker in ordered_workers:
        distance_km = calculate_distance_km(
            worker.current_latitude or (worker.branch.latitude if worker.branch else None),
            worker.current_longitude or (worker.branch.longitude if worker.branch else None),
            incident.incident_latitude,
            incident.incident_longitude,
        )
        cost_breakdown = calculate_service_cost(incident=incident, distance_km=distance_km or Decimal("5.00"), status_name="asignado")
        worker_offer = money(max(incident.estimated_cost or Decimal("0"), cost_breakdown["total"] * Decimal("0.96")))
        eta_minutes = max(8, int((distance_km or Decimal("5.00")) * Decimal("3.0")) + 6)
        offers.append(
            TechnicianOfferItem(
                worker_id=worker.id,
                worker_name=f"{worker.first_name} {worker.last_name}",
                specialty=worker.main_specialty,
                rating=worker.average_rating,
                distance_km=distance_km,
                eta_minutes=eta_minutes,
                suggested_price=cost_breakdown["total"],
                worker_offer=worker_offer,
                status=worker.operational_status.name if worker.operational_status else None,
            )
        )
    return offers


@router.post("/{incident_id}/select-technician", response_model=IncidentDetailResponse)
async def select_technician_offer(
    incident_id: int,
    payload: TechnicianSelect,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.CLIENT, AccountRoleName.ADMIN)),
) -> IncidentDetailResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
        )
        .where(Incident.id == incident_id)
    )
    worker = await session.scalar(
        select(Worker)
        .options(selectinload(Worker.operational_status), selectinload(Worker.branch))
        .where(Worker.id == payload.worker_id)
    )
    if not incident or not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente o tecnico no encontrado.")
    if current_user.primary_role == AccountRoleName.CLIENT.value and incident.client.account_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes seleccionar tecnico para este incidente.")
    if not worker.is_available or (worker.operational_status and worker.operational_status.name != "libre"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El tecnico ya no esta libre.")

    status_row = await get_status_by_name(session, "tecnico_asignado")
    old_status_id = incident.status_id
    incident.assigned_worker_id = worker.id
    incident.assigned_workshop_id = worker.workshop_id
    incident.assigned_branch_id = worker.branch_id
    incident.status_id = status_row.id
    incident.assigned_at = datetime.utcnow()
    incident.accepted_at = datetime.utcnow()
    incident.estimated_cost = payload.agreed_price or incident.estimated_cost
    distance_km = calculate_distance_km(
        worker.current_latitude or (worker.branch.latitude if worker.branch else None),
        worker.current_longitude or (worker.branch.longitude if worker.branch else None),
        incident.incident_latitude,
        incident.incident_longitude,
    )
    if distance_km is not None:
        incident.workshop_distance_km = distance_km
        incident.eta_minutes = max(8, int(distance_km * Decimal("3.0")) + 6)
        incident.eta_at = datetime.utcnow() + timedelta(minutes=incident.eta_minutes)
        incident.eta_last_calculated_at = datetime.utcnow()
    cost_breakdown = calculate_service_cost(incident=incident, distance_km=distance_km or Decimal("5.00"), status_name="tecnico_asignado")
    candidates = await build_ai_assignment_candidates(
        session=session,
        incident=incident,
        required_specialty=incident.final_classification or worker.main_specialty or "motor",
        limit=5,
    )
    matching_candidate = next((candidate for candidate in candidates if candidate.workshop_id == worker.workshop_id), None)
    session.add(
        Assignment(
            incident_id=incident.id,
            candidate_workshop_id=worker.workshop_id,
            assignment_score=matching_candidate.score if matching_candidate else Decimal("90.00"),
            used_criteria=matching_candidate.criteria if matching_candidate else {
                "selected_by_client": True,
                "distance_km": float(distance_km or Decimal("0")),
                "worker_specialty": worker.main_specialty,
            },
            was_selected=True,
        )
    )
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="asignacion",
            model_provider=LOCAL_AI_PROVIDER,
            model_version=LOCAL_AI_VERSION,
            input_summary=f"Cliente selecciono tecnico {worker.id}; distancia {distance_km} km.",
            output_summary=(
                f"CU21: tecnico {worker.first_name} {worker.last_name} asignado. "
                f"ETA {incident.eta_minutes or 'N/D'} min. Costo estimado Bs. {payload.agreed_price or cost_breakdown['total']}."
            ),
            confidence=matching_candidate.score if matching_candidate else Decimal("90.00"),
            duration_ms=110,
            is_final_result=True,
        )
    )

    await set_worker_operational_status(
        session=session,
        worker=worker,
        status_name="en_camino",
        current_user=current_user,
        notes="Tecnico elegido por el cliente",
    )
    session.add(
        WorkerAssignmentHistory(
            incident_id=incident.id,
            worker_id=worker.id,
            branch_id=worker.branch_id,
            is_current=True,
            action_account_id=current_user.id,
            reason="Seleccion directa del cliente",
        )
    )
    session.add(
        IncidentStatusHistory(
            incident_id=incident.id,
            old_status_id=old_status_id,
            new_status_id=status_row.id,
            action_account_id=current_user.id,
            notes="Cliente selecciono oferta de tecnico",
        )
    )
    await create_notification(
        session=session,
        account_ids=[worker.account_id] if worker.account_id else [],
        title="Nuevo servicio elegido",
        message=f"El cliente eligio tu oferta para el incidente #{incident.id}.",
        notification_type="tecnico_seleccionado",
        incident_id=incident.id,
        extra_data={"expires_in_seconds": 20},
    )
    await session.commit()
    return await get_incident_detail(incident.id, session)


@router.post("/{incident_id}/ai/process", response_model=AIProcessResponse)
async def process_incident_with_ai(
    incident_id: int,
    session: AsyncSession = Depends(get_db_session),
    _current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> AIProcessResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
            selectinload(Incident.evidences),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")

    incident, analysis = await apply_local_ai_processing(session=session, incident=incident)
    candidates = await build_ai_assignment_candidates(
        session=session,
        incident=incident,
        required_specialty=analysis.required_specialty,
    )
    add_assignment_rankings(
        session=session,
        incident=incident,
        candidates=candidates,
        selected_workshop_id=incident.assigned_workshop_id,
    )
    session.add(
        AIInference(
            incident_id=incident.id,
            process_type="asignacion",
            model_provider=LOCAL_AI_PROVIDER,
            model_version=LOCAL_AI_VERSION,
            input_summary=f"Reproceso manual IA. Especialidad requerida {analysis.required_specialty}.",
            output_summary=f"CU21: {len(candidates)} candidatos rankeados para el incidente.",
            confidence=candidates[0].score if candidates else Decimal("45.00"),
            duration_ms=150,
            is_final_result=bool(candidates),
        )
    )
    await session.commit()
    return AIProcessResponse(
        incident_id=incident.id,
        incident_type=analysis.incident_type,
        required_specialty=analysis.required_specialty,
        priority=analysis.suggested_priority,
        confidence=analysis.confidence,
        summary=analysis.summary,
        risk_signals=analysis.risk_signals,
        matched_keywords=analysis.matched_keywords,
        assignment_candidates=[
            {
                "workshop_id": candidate.workshop_id,
                "workshop_name": candidate.workshop_name,
                "branch_id": candidate.branch_id,
                "branch_name": candidate.branch_name,
                "worker_id": candidate.worker_id,
                "worker_name": candidate.worker_name,
                "score": candidate.score,
                "distance_km": candidate.distance_km,
                "eta_minutes": candidate.eta_minutes,
                "criteria": candidate.criteria,
                "reason": candidate.reason,
            }
            for candidate in candidates
        ],
    )


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
            selectinload(Incident.assigned_worker).selectinload(Worker.operational_status),
            selectinload(Incident.assigned_worker).selectinload(Worker.branch),
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
                "operational_status": incident.assigned_worker.operational_status.name if incident.assigned_worker.operational_status else None,
                "lat": incident.assigned_worker.current_latitude,
                "lng": incident.assigned_worker.current_longitude,
                "last_location_at": incident.assigned_worker.last_location_at,
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
                "criteria": item.used_criteria,
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


@router.get("/{incident_id}/tracking", response_model=TrackingResponse)
async def get_incident_tracking(
    incident_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(
        require_roles(
            AccountRoleName.CLIENT,
            AccountRoleName.WORKSHOP_OWNER,
            AccountRoleName.WORKER,
            AccountRoleName.ADMIN,
        )
    ),
) -> TrackingResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_worker).selectinload(Worker.operational_status),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
            selectinload(Incident.status),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if not can_access_incident_chat_or_tracking(incident, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes acceder al tracking de este incidente.")

    return TrackingResponse(
        incident_id=incident.id,
        status=incident.status.name,
        eta_minutes=incident.eta_minutes,
        eta_at=incident.eta_at,
        incident_coordinates={
            "lat": incident.incident_latitude,
            "lng": incident.incident_longitude,
        },
        worker=(
            {
                "id": incident.assigned_worker.id,
                "name": f"{incident.assigned_worker.first_name} {incident.assigned_worker.last_name}",
                "phone": incident.assigned_worker.phone,
                "specialty": incident.assigned_worker.main_specialty,
                "operational_status": incident.assigned_worker.operational_status.name if incident.assigned_worker.operational_status else None,
                "lat": incident.assigned_worker.current_latitude,
                "lng": incident.assigned_worker.current_longitude,
                "last_location_at": incident.assigned_worker.last_location_at,
            }
            if incident.assigned_worker
            else None
        ),
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
    )


@router.post("/{incident_id}/tracking/worker-location", response_model=TrackingResponse)
async def update_worker_location(
    incident_id: int,
    payload: WorkerLocationUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKER, AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> TrackingResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_worker).selectinload(Worker.operational_status),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
            selectinload(Incident.status),
        )
        .where(Incident.id == incident_id)
    )
    if not incident or not incident.assigned_worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente o trabajador asignado no encontrado.")

    is_worker = incident.assigned_worker.account_id == current_user.id
    is_workshop_owner = incident.assigned_workshop and any(
        link.owner.account_id == current_user.id for link in incident.assigned_workshop.owner_links
    )
    if current_user.primary_role != AccountRoleName.ADMIN.value and not is_worker and not is_workshop_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes actualizar esta ubicacion.")

    incident.assigned_worker.current_latitude = payload.latitude
    incident.assigned_worker.current_longitude = payload.longitude
    incident.assigned_worker.last_location_at = datetime.utcnow()
    incident.eta_last_calculated_at = datetime.utcnow()
    await session.commit()

    return await get_incident_tracking(incident_id, session, current_user)


@router.get("/{incident_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_messages(
    incident_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(
        require_roles(
            AccountRoleName.CLIENT,
            AccountRoleName.WORKSHOP_OWNER,
            AccountRoleName.WORKER,
            AccountRoleName.ADMIN,
        )
    ),
) -> list[ChatMessageResponse]:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_worker),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if not can_access_incident_chat_or_tracking(incident, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes acceder al chat de este incidente.")

    messages = (
        await session.scalars(
            select(IncidentChatMessage)
            .where(IncidentChatMessage.incident_id == incident_id)
            .order_by(IncidentChatMessage.sent_at.asc(), IncidentChatMessage.id.asc())
        )
    ).all()
    return [serialize_chat_message(message) for message in messages]


@router.post("/{incident_id}/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_chat_message(
    incident_id: int,
    payload: ChatMessageCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(
        require_roles(
            AccountRoleName.CLIENT,
            AccountRoleName.WORKSHOP_OWNER,
            AccountRoleName.WORKER,
            AccountRoleName.ADMIN,
        )
    ),
) -> ChatMessageResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_worker),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if not can_access_incident_chat_or_tracking(incident, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes enviar mensajes en este incidente.")

    message = IncidentChatMessage(
        incident_id=incident_id,
        sender_account_id=current_user.id,
        sender_role=current_user.primary_role or "usuario",
        sender_name=current_user.display_name,
        message_text=payload.message_text.strip(),
    )
    session.add(message)
    await session.flush()

    recipients = [incident.client.account_id]
    if incident.assigned_worker and incident.assigned_worker.account_id:
        recipients.append(incident.assigned_worker.account_id)
    if incident.assigned_workshop:
        recipients.extend(link.owner.account_id for link in incident.assigned_workshop.owner_links)

    await create_notification(
        session=session,
        account_ids=[account_id for account_id in recipients if account_id != current_user.id],
        title="Nuevo mensaje en tu asistencia",
        message=f"{current_user.display_name}: {payload.message_text.strip()}",
        notification_type="chat",
        incident_id=incident.id,
    )
    await session.commit()
    await session.refresh(message)
    return serialize_chat_message(message)


@router.post("/{incident_id}/ratings", response_model=ServiceRatingResponse, status_code=status.HTTP_201_CREATED)
async def rate_service(
    incident_id: int,
    payload: ServiceRatingCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.CLIENT)),
) -> ServiceRatingResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_worker),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
            selectinload(Incident.status),
            selectinload(Incident.workshop_rating),
            selectinload(Incident.worker_rating),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if incident.client.account_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el cliente del incidente puede calificar.")
    if incident.status.name != "finalizado":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Solo se puede calificar un servicio finalizado.")
    if incident.workshop_rating or incident.worker_rating:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este servicio ya fue calificado.")
    if not incident.assigned_workshop or not incident.assigned_worker:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El servicio no tiene taller o tecnico asignado.")

    workshop_rating = WorkshopRating(
        incident_id=incident.id,
        workshop_id=incident.assigned_workshop_id,
        client_id=incident.client_id,
        score=payload.workshop_score,
        comment=payload.comment,
    )
    worker_rating = WorkerRating(
        incident_id=incident.id,
        worker_id=incident.assigned_worker_id,
        client_id=incident.client_id,
        score=payload.worker_score,
        comment=payload.comment,
        punctuality=payload.punctuality,
        work_quality=payload.work_quality,
        customer_service=payload.customer_service,
    )
    session.add(workshop_rating)
    session.add(worker_rating)

    workshop = incident.assigned_workshop
    workshop.average_rating = (
        (workshop.average_rating * workshop.total_ratings) + Decimal(payload.workshop_score)
    ) / Decimal(workshop.total_ratings + 1)
    workshop.total_ratings += 1

    worker = incident.assigned_worker
    worker.average_rating = (
        (worker.average_rating * worker.total_ratings) + Decimal(payload.worker_score)
    ) / Decimal(worker.total_ratings + 1)
    worker.total_ratings += 1

    await create_notification(
        session=session,
        account_ids=[
            link.owner.account_id for link in incident.assigned_workshop.owner_links
        ] + ([worker.account_id] if worker.account_id else []),
        title="Nuevo rating recibido",
        message=f"El servicio del incidente #{incident.id} recibió una nueva calificación.",
        notification_type="rating",
        incident_id=incident.id,
    )
    await session.commit()

    rated_at = worker_rating.rated_at or workshop_rating.rated_at or datetime.utcnow()
    return ServiceRatingResponse(
        incident_id=incident.id,
        workshop_score=payload.workshop_score,
        worker_score=payload.worker_score,
        comment=payload.comment,
        rated_at=rated_at,
    )


@router.post("/{incident_id}/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident_payment(
    incident_id: int,
    payload: PaymentCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.CLIENT)),
) -> PaymentResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client).selectinload(User.account),
            selectinload(Incident.assigned_workshop).selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner),
            selectinload(Incident.payments).selectinload(Payment.status),
        )
        .where(Incident.id == incident_id)
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if incident.client.account_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el cliente del incidente puede pagar este servicio.")
    if not incident.assigned_workshop_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El incidente aún no tiene taller asignado.")
    if any(payment.status and payment.status.name == "pagado" for payment in incident.payments):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este servicio ya tiene un pago confirmado.")

    paid_status = await session.scalar(select(PaymentStatus).where(PaymentStatus.name == "pagado"))
    if not paid_status:
        paid_status = PaymentStatus(name="pagado")
        session.add(paid_status)
        await session.flush()

    method_name = payload.payment_method.strip().lower()
    payment_method = await session.scalar(select(PaymentMethod).where(PaymentMethod.name == method_name))
    if not payment_method:
        payment_method = PaymentMethod(
            name=method_name,
            description=f"Método de pago {method_name}",
            is_active=True,
        )
        session.add(payment_method)
        await session.flush()

    platform_fee = (payload.total_amount * Decimal("0.10")).quantize(Decimal("0.01"))
    workshop_amount = payload.total_amount - platform_fee
    payment = Payment(
        incident_id=incident.id,
        client_id=incident.client_id,
        workshop_id=incident.assigned_workshop_id,
        total_amount=payload.total_amount,
        platform_fee=platform_fee,
        workshop_amount=workshop_amount,
        status_id=paid_status.id,
        payment_method_id=payment_method.id,
        external_transaction_id=payload.external_transaction_id,
        confirmed_at=datetime.utcnow(),
        created_by=current_user.email,
    )
    session.add(payment)
    incident.final_cost = payload.total_amount
    await session.flush()

    recipients = [incident.client.account_id]
    if incident.assigned_workshop:
        recipients.extend(link.owner.account_id for link in incident.assigned_workshop.owner_links)
    await create_notification(
        session=session,
        account_ids=recipients,
        title="Pago confirmado",
        message=f"Se registró el pago del incidente #{incident.id} por Bs. {payload.total_amount}.",
        notification_type="pago",
        incident_id=incident.id,
    )
    await session.commit()
    await session.refresh(payment)

    return PaymentResponse(
        id=payment.id,
        incident_id=payment.incident_id,
        total_amount=payment.total_amount,
        platform_fee=payment.platform_fee,
        workshop_amount=payment.workshop_amount,
        status=paid_status.name,
        payment_method=payment_method.name,
        requested_at=payment.requested_at,
        confirmed_at=payment.confirmed_at,
    )


@router.patch("/{incident_id}/decision", response_model=IncidentDetailResponse)
async def decide_emergency(
    incident_id: int,
    payload: EmergencyDecision,
    session: AsyncSession = Depends(get_db_session),
    current_user: Account = Depends(require_roles(AccountRoleName.WORKSHOP_OWNER, AccountRoleName.ADMIN)),
) -> IncidentDetailResponse:
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client),
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
            selectinload(Incident.evidences),
            selectinload(Incident.assigned_worker).selectinload(Worker.operational_status),
            selectinload(Incident.assigned_branch),
        )
        .where(Incident.id == incident_id)
    )
    workshop = await session.get(Workshop, payload.workshop_id)
    client = await session.get(User, incident.client_id) if incident else None
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    if not workshop or not workshop.is_available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no disponible.")
    status_name = "asignado" if payload.accepted else "rechazado"
    new_status = await get_status_by_name(session, status_name)
    old_status_id = incident.status_id
    primary_branch = await session.scalar(select(WorkshopBranch).where(WorkshopBranch.workshop_id == workshop.id).order_by(WorkshopBranch.id))
    ai_analysis = analyze_incident(
        description_text=incident.description_text,
        address_text=incident.address_text,
        manual_incident_type=incident.final_classification or incident.manual_incident_type_name,
        evidences=incident.evidences,
        requested_priority=incident.priority.name,
    )
    candidates = await build_ai_assignment_candidates(
        session=session,
        incident=incident,
        required_specialty=ai_analysis.required_specialty,
        limit=5,
    )
    matching_candidate = next((candidate for candidate in candidates if candidate.workshop_id == workshop.id), None)
    assignment = Assignment(
        incident_id=incident.id,
        candidate_workshop_id=workshop.id,
        assignment_score=matching_candidate.score if matching_candidate else (Decimal("92.50") if payload.accepted else Decimal("45.00")),
        used_criteria=matching_candidate.criteria if matching_candidate else {"distance": 35, "capacity": 25, "rating": 20, "availability": 20},
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
        branch_latitude = primary_branch.latitude if primary_branch else workshop.latitude
        branch_longitude = primary_branch.longitude if primary_branch else workshop.longitude
        distance_km = calculate_distance_km(
            branch_latitude,
            branch_longitude,
            incident.incident_latitude,
            incident.incident_longitude,
        ) or Decimal("8.50")
        cost_breakdown = calculate_service_cost(incident=incident, distance_km=distance_km, status_name=status_name)
        incident.accepted_at = datetime.utcnow()
        incident.eta_minutes = max(10, int(distance_km * Decimal("3.2")) + 8)
        incident.eta_at = datetime.utcnow() + timedelta(minutes=incident.eta_minutes)
        incident.eta_last_calculated_at = datetime.utcnow()
        incident.workshop_distance_km = distance_km
        incident.estimated_cost = cost_breakdown["total"]
        session.add(
            AIInference(
                incident_id=incident.id,
                process_type="asignacion",
                model_provider="rule-engine",
                model_version="v1",
                input_summary="Asignacion por disponibilidad, cobertura, distancia y demanda",
                output_summary=(
                    f"Taller {workshop.trade_name} seleccionado con ETA {incident.eta_minutes} minutos. "
                    f"Costo estimado Bs. {cost_breakdown['total']} "
                    f"(base {cost_breakdown['base_service']}, distancia {cost_breakdown['distance']}, "
                    f"demanda {cost_breakdown['demand']}, operativo {cost_breakdown['operating']})."
                ),
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
    await create_notification(
        session=session,
        account_ids=[client.account_id] if client else [],
        title="Actualización de emergencia",
        message=(
            f"Tu incidente fue asignado al taller {workshop.trade_name}."
            if payload.accepted
            else "Tu solicitud fue rechazada y será reevaluada por la plataforma."
        ),
        notification_type="estado_cambiado",
        incident_id=incident.id,
        extra_data={"status": new_status.name},
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
    incident = await session.scalar(
        select(Incident)
        .options(
            selectinload(Incident.client),
            selectinload(Incident.priority),
            selectinload(Incident.manual_incident_type),
            selectinload(Incident.final_incident_type),
            selectinload(Incident.assigned_worker).selectinload(Worker.operational_status),
            selectinload(Incident.assigned_worker).selectinload(Worker.branch),
            selectinload(Incident.assigned_branch),
        )
        .where(Incident.id == incident_id)
    )
    client = await session.get(User, incident.client_id) if incident else None
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado.")
    new_status = await get_status_by_name(session, payload.status_name)
    old_status_id = incident.status_id
    incident.status_id = new_status.id
    worker: Worker | None = None
    if payload.worker_id:
        worker = await session.scalar(
            select(Worker)
            .options(selectinload(Worker.operational_status), selectinload(Worker.branch))
            .where(Worker.id == payload.worker_id)
        )
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
    elif current_user.primary_role == AccountRoleName.WORKER.value:
        worker = await session.scalar(
            select(Worker)
            .options(selectinload(Worker.operational_status), selectinload(Worker.branch))
            .where(Worker.account_id == current_user.id)
        )
        if worker:
            incident.assigned_branch_id = worker.branch_id
            incident.assigned_worker_id = worker.id
            incident.assigned_workshop_id = incident.assigned_workshop_id or worker.workshop_id
    else:
        worker = incident.assigned_worker

    if worker and not incident.assigned_worker_id:
        incident.assigned_worker_id = worker.id
        incident.assigned_branch_id = worker.branch_id
        incident.assigned_workshop_id = incident.assigned_workshop_id or worker.workshop_id

    if worker:
        next_worker_status = worker_status_from_incident_status(payload.status_name)
        if next_worker_status:
            await set_worker_operational_status(
                session=session,
                worker=worker,
                status_name=next_worker_status,
                current_user=current_user,
                notes=payload.notes or f"Sincronizado por estado de incidente {payload.status_name}",
            )

        origin_latitude = worker.current_latitude or (worker.branch.latitude if worker.branch else None)
        origin_longitude = worker.current_longitude or (worker.branch.longitude if worker.branch else None)
        distance_km = calculate_distance_km(
            origin_latitude,
            origin_longitude,
            incident.incident_latitude,
            incident.incident_longitude,
        )
        if distance_km is not None:
            incident.workshop_distance_km = distance_km
            cost_breakdown = calculate_service_cost(incident=incident, distance_km=distance_km, status_name=payload.status_name)
            if payload.status_name == "finalizado":
                incident.final_cost = cost_breakdown["total"]
            else:
                incident.estimated_cost = cost_breakdown["total"]
            session.add(
                AIInference(
                    incident_id=incident.id,
                    process_type="costeo_servicio",
                    model_provider="rule-engine",
                    model_version="v2",
                    input_summary=f"Estado {payload.status_name}, distancia {distance_km} km y prioridad {incident.priority.name}",
                    output_summary=(
                        f"Costo {'final' if payload.status_name == 'finalizado' else 'estimado'} Bs. {cost_breakdown['total']} "
                        f"= base {cost_breakdown['base_service']} + distancia {cost_breakdown['distance']} + "
                        f"demanda {cost_breakdown['demand']} + operativo {cost_breakdown['operating']} + "
                        f"fee {cost_breakdown['platform_fee']}."
                    ),
                    confidence=Decimal("90.00"),
                    duration_ms=95,
                    is_final_result=payload.status_name == "finalizado",
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
    await create_notification(
        session=session,
        account_ids=[client.account_id] if client else [],
        title="Estado actualizado",
        message=f"Tu emergencia ahora está en estado: {new_status.name}.",
        notification_type="estado_cambiado",
        incident_id=incident.id,
        extra_data={"status": new_status.name},
    )
    await session.commit()
    return await get_incident_detail(incident.id, session)

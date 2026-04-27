from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import db_session
from app.models import (
    Account,
    AccountRole,
    Administrator,
    AdminEvent,
    AIInference,
    Assignment,
    AuthSession,
    DailyMetric,
    Evidence,
    Incident,
    IncidentChatMessage,
    IncidentStatus,
    IncidentStatusHistory,
    IncidentType,
    LoginAttempt,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Permission,
    Priority,
    PushDevice,
    Role,
    RolePermission,
    Specialty,
    User,
    Vehicle,
    Worker,
    WorkerAssignmentHistory,
    WorkerRating,
    WorkerSpecialty,
    WorkerStatus,
    WorkerStatusHistory,
    Workshop,
    WorkshopAvailabilityHistory,
    WorkshopAvailabilityState,
    WorkshopBranch,
    WorkshopOwner,
    WorkshopOwnerLink,
    WorkshopRating,
)
from app.models.user import AccountRoleName, ExperienceLevel, VehicleType


DEFAULT_PASSWORD = "password123"
SEED_EMAIL_DOMAIN = "seed.com"
DEMO_CLIENT_EMAIL = "cliente@test.com"
DEMO_WORKSHOP_EMAIL = "taller@test.com"
DEMO_WORKER_EMAIL = "tecnico@test.com"
DEMO_ADMIN_EMAIL = "admin@test.com"
CLIENT_COUNT = 60
OWNER_COUNT = 28
WORKSHOP_COUNT = 28
BRANCHES_PER_WORKSHOP = 3
WORKERS_PER_WORKSHOP = 5
ADMIN_COUNT = 8
VEHICLE_COUNT = 150
INCIDENT_COUNT = 180

FIRST_NAMES = ["Ana", "Luis", "Carla", "Mateo", "Sofia", "Diego", "Valeria", "Jorge", "Camila", "Andres", "Paola", "Marco", "Daniela", "Rodrigo", "Gabriela", "Hugo"]
LAST_NAMES = ["Rojas", "Mendoza", "Lopez", "Vargas", "Flores", "Quispe", "Aguilar", "Soria", "Suarez", "Torrez", "Rivera", "Mamani", "Arce", "Salazar"]
CITIES = ["Santa Cruz de la Sierra"]
ZONES = [
    "Equipetrol",
    "Sirari",
    "Las Palmas",
    "Urubo",
    "Plan 3000",
    "Villa Primero de Mayo",
    "Los Lotes",
    "El Trompillo",
    "Hamacas",
    "Centro",
    "Mutualista",
    "Doble Via La Guardia",
]
AVENUES = [
    "Av. Cristo Redentor",
    "Av. San Martin",
    "Av. Beni",
    "Av. Banzer",
    "Av. Virgen de Cotoca",
    "Av. Grigota",
    "Av. Santos Dumont",
    "Av. Roca y Coronado",
]
SPECIALTY_DATA = [
    ("bateria", "Diagnostico y cambio de baterias"),
    ("llanta", "Pinchazos, inflado y reemplazo"),
    ("motor", "Fallas mecanicas y sobrecalentamiento"),
    ("choque", "Golpes leves y auxilio de chapa"),
    ("electrico", "Sistema electrico automotriz"),
    ("cerradura", "Llaves perdidas o encerradas"),
    ("remolque", "Asistencia con traslado"),
]
PAYMENT_METHODS = [
    ("qr_bcb", "QR interoperable BCB"),
    ("tarjeta", "Pago con tarjeta"),
    ("transferencia", "Transferencia bancaria"),
    ("efectivo", "Pago en efectivo"),
]
WORKSHOP_AVAILABILITY_STATES = [
    ("disponible", "Puede recibir nuevas solicitudes"),
    ("saturado", "Tiene capacidad completa"),
    ("cerrado", "No atiende por horario"),
    ("pausado", "Suspendido temporalmente"),
    ("inactivo", "Deshabilitado en la plataforma"),
]
WORKER_STATUSES = [
    ("libre", "Disponible para recibir asignaciones"),
    ("en_camino", "Ya fue asignado y se dirige al incidente"),
    ("en_servicio", "Atendiendo un incidente"),
    ("fuera_turno", "No esta trabajando"),
    ("pausado", "Disponible temporalmente desactivado"),
    ("desconectado", "Sin sesion o sin ubicacion actual"),
]
PERMISSIONS_BY_ROLE = {
    AccountRoleName.CLIENT.value: [
        ("auth.login", "Iniciar sesion"),
        ("auth.logout", "Cerrar sesion"),
        ("cliente.registrar", "Registrarse como cliente"),
        ("cliente.vehiculo.crear", "Registrar vehiculo"),
        ("incidente.crear", "Reportar emergencia"),
        ("incidente.evidencia.crear", "Adjuntar evidencias"),
        ("incidente.consultar.estado", "Consultar estado de solicitud"),
        ("incidente.consultar.eta", "Ver taller asignado y tiempo estimado"),
        ("pago.crear", "Realizar pago"),
        ("notificacion.recibir", "Recibir notificaciones"),
    ],
    AccountRoleName.WORKSHOP_OWNER.value: [
        ("auth.login", "Iniciar sesion"),
        ("auth.logout", "Cerrar sesion"),
        ("taller.registrar", "Registrarse como taller"),
        ("taller.disponibilidad.gestionar", "Gestionar disponibilidad del taller"),
        ("taller.solicitudes.ver", "Visualizar solicitudes disponibles"),
        ("taller.ficha.ver", "Revisar ficha estructurada del incidente"),
        ("taller.solicitud.responder", "Aceptar o rechazar solicitud"),
        ("taller.servicio.estado.actualizar", "Actualizar estado del servicio"),
        ("taller.historial.ver", "Consultar historial de atenciones"),
        ("notificacion.recibir", "Recibir notificaciones"),
    ],
    AccountRoleName.WORKER.value: [
        ("auth.login", "Iniciar sesion"),
        ("auth.logout", "Cerrar sesion"),
        ("taller.ficha.ver", "Revisar ficha estructurada del incidente"),
        ("taller.servicio.estado.actualizar", "Actualizar estado del servicio"),
        ("notificacion.recibir", "Recibir notificaciones"),
    ],
    AccountRoleName.ADMIN.value: [
        ("auth.login", "Iniciar sesion"),
        ("auth.logout", "Cerrar sesion"),
        ("admin.usuarios_talleres.gestionar", "Gestionar usuarios y talleres"),
        ("admin.metricas.ver", "Monitorear metricas y trazabilidad"),
        ("notificacion.recibir", "Recibir notificaciones"),
    ],
}
INCIDENT_STATUSES = [
    ("pendiente", "Emergencia reportada, esperando asignacion", 1, False),
    ("asignado", "Taller asignado, esperando confirmacion", 2, False),
    ("tecnico_asignado", "Tecnico especifico asignado", 3, False),
    ("en_camino", "Tecnico en camino", 4, False),
    ("trabajando", "Servicio en ejecucion", 5, False),
    ("finalizado", "Servicio completado", 6, True),
    ("rechazado", "Solicitud rechazada", 7, True),
]
CAR_BRANDS = {
    "Toyota": ["Corolla", "Hilux", "Yaris"],
    "Suzuki": ["Swift", "Vitara", "Jimny"],
    "Nissan": ["Versa", "Sentra", "Frontier"],
    "Kia": ["Rio", "Sportage", "Soluto"],
    "Hyundai": ["Accent", "Creta", "Tucson"],
}


@dataclass
class SeedResult:
    accounts: int
    clients: int
    owners: int
    admins: int
    workshops: int
    branches: int
    workers: int
    vehicles: int
    incidents: int
    payments: int
    notifications: int


def phone(index: int) -> str:
    return f"7{6000000 + index:07d}"


def name_pair(index: int) -> tuple[str, str]:
    first = FIRST_NAMES[index % len(FIRST_NAMES)]
    last = f"{LAST_NAMES[index % len(LAST_NAMES)]} {LAST_NAMES[(index + 2) % len(LAST_NAMES)]}"
    return first, last


def geo_offset(base: str, index: int, step: str = "0.0012") -> Decimal:
    return Decimal(base) + Decimal(index) * Decimal(step)


async def seed_catalogs(session: AsyncSession) -> dict[str, dict[str, object] | list[Specialty]]:
    roles = [
        Role(name=AccountRoleName.CLIENT.value, description="Cliente que reporta emergencias"),
        Role(name=AccountRoleName.WORKSHOP_OWNER.value, description="Dueño o responsable principal del taller"),
        Role(name=AccountRoleName.WORKER.value, description="Tecnico del taller"),
        Role(name=AccountRoleName.ADMIN.value, description="Administrador de la plataforma"),
    ]
    priorities = [
        Priority(name="alta", level=1, max_response_minutes=30),
        Priority(name="media", level=2, max_response_minutes=60),
        Priority(name="baja", level=3, max_response_minutes=120),
    ]
    incident_statuses = [
        IncidentStatus(name=name, description=description, visual_order=order, is_final=is_final)
        for name, description, order, is_final in INCIDENT_STATUSES
    ]
    payment_statuses = [PaymentStatus(name=name) for name in ["pendiente", "pagado", "fallido", "reembolsado"]]
    payment_methods = [PaymentMethod(name=name, description=description) for name, description in PAYMENT_METHODS]
    incident_types = [IncidentType(name=name, description=description) for name, description in SPECIALTY_DATA]
    incident_types.append(IncidentType(name="otro", description="Otro tipo de incidente"))
    permissions = [Permission(code=code, description=description) for entries in PERMISSIONS_BY_ROLE.values() for code, description in entries]
    deduped_permissions: dict[str, Permission] = {permission.code: permission for permission in permissions}
    workshop_availability_states = [
        WorkshopAvailabilityState(name=name, description=description)
        for name, description in WORKSHOP_AVAILABILITY_STATES
    ]
    worker_statuses = [WorkerStatus(name=name, description=description) for name, description in WORKER_STATUSES]
    specialties = [Specialty(name=name, description=description) for name, description in SPECIALTY_DATA]

    session.add_all([
        *roles,
        *priorities,
        *incident_statuses,
        *payment_statuses,
        *payment_methods,
        *incident_types,
        *deduped_permissions.values(),
        *workshop_availability_states,
        *worker_statuses,
        *specialties,
    ])
    await session.flush()
    role_permission_links = [
        RolePermission(
            role_id=next(role.id for role in roles if role.name == role_name),
            permission_id=deduped_permissions[code].id,
        )
        for role_name, entries in PERMISSIONS_BY_ROLE.items()
        for code, _description in entries
    ]
    session.add_all(role_permission_links)
    await session.flush()

    return {
        "roles": {item.name: item for item in roles},
        "permissions": {item.code: item for item in deduped_permissions.values()},
        "priorities": {item.name: item for item in priorities},
        "incident_statuses": {item.name: item for item in incident_statuses},
        "payment_statuses": {item.name: item for item in payment_statuses},
        "payment_methods": {item.name: item for item in payment_methods},
        "incident_types": {item.name: item for item in incident_types},
        "workshop_availability_states": {item.name: item for item in workshop_availability_states},
        "worker_statuses": {item.name: item for item in worker_statuses},
        "specialties": specialties,
    }


async def create_account(session: AsyncSession, *, email: str, role: Role, phone_number: str, verified: bool = True) -> Account:
    account = Account(
        email=email,
        phone=phone_number,
        password_hash=hash_password(DEFAULT_PASSWORD),
        is_verified=verified,
        is_active=True,
    )
    session.add(account)
    await session.flush()
    session.add(AccountRole(account_id=account.id, role_id=role.id))
    await session.flush()
    return account


async def seed_clients(session: AsyncSession, roles: dict[str, Role]) -> list[User]:
    clients: list[User] = []
    for index in range(CLIENT_COUNT):
        first, last = name_pair(index)
        account = await create_account(
            session,
            email=DEMO_CLIENT_EMAIL if index == 0 else f"cliente{index + 1:02d}@{SEED_EMAIL_DOMAIN}",
            role=roles[AccountRoleName.CLIENT.value],
            phone_number=phone(index),
        )
        clients.append(User(account_id=account.id, first_name=first, last_name=last))
    session.add_all(clients)
    await session.flush()
    return clients


async def seed_owners_and_workshops(
    session: AsyncSession,
    roles: dict[str, Role],
    availability_states: dict[str, WorkshopAvailabilityState],
) -> tuple[list[WorkshopOwner], list[Workshop], list[WorkshopBranch]]:
    owners: list[WorkshopOwner] = []
    workshops: list[Workshop] = []
    branches: list[WorkshopBranch] = []
    for index in range(OWNER_COUNT):
        first, last = name_pair(index + 40)
        city = CITIES[index % len(CITIES)]
        owner_account = await create_account(
            session,
            email=DEMO_WORKSHOP_EMAIL if index == 0 else f"taller{index + 1:02d}@{SEED_EMAIL_DOMAIN}",
            role=roles[AccountRoleName.WORKSHOP_OWNER.value],
            phone_number=phone(index + 40),
        )
        owner = WorkshopOwner(
            account_id=owner_account.id,
            first_name=first,
            last_name=last,
            national_id=f"CI-{7800000 + index}",
            phone=owner_account.phone,
        )
        workshop = Workshop(
            trade_name=f"Taller Movil {index + 1:02d}",
            legal_name=f"Servicios Automotrices {index + 1:02d} SRL",
            tax_id=f"NIT-{950000 + index}",
            email=owner_account.email,
            phone=owner_account.phone or phone(index + 140),
            address=f"{AVENUES[index % len(AVENUES)]}, {ZONES[index % len(ZONES)]}, 3er anillo #{120 + index}",
            city=city,
            latitude=geo_offset("-17.78332700", index),
            longitude=geo_offset("-63.18214000", index, "0.0011"),
            coverage_radius_km=25 + (index % 3) * 5,
            opening_time=time(8, 0),
            closing_time=time(20, 0),
            serves_24h=index % 4 == 0,
            max_concurrent_capacity=3 + (index % 3),
            is_active=True,
            is_available=index % 5 != 0,
            is_admin_approved=index % 6 != 0,
            approved_at=datetime.utcnow() - timedelta(days=index) if index % 6 != 0 else None,
            approval_notes="Aprobado para operar" if index % 6 != 0 else "Pendiente de revision documental",
            availability_state_id=availability_states["disponible"].id if index % 5 != 0 else availability_states["pausado"].id,
            current_concurrent_capacity=index % 3,
            accepts_requests=index % 5 != 0,
            average_rating=Decimal("3.80") + Decimal(index % 9) / Decimal("10"),
            total_ratings=12 + index,
        )
        owners.append(owner)
        workshops.append(workshop)
        session.add_all([owner, workshop])
        await session.flush()
        workshop.primary_owner_id = owner.id
        session.add(WorkshopOwnerLink(owner_id=owner.id, workshop_id=workshop.id, is_primary=True))
        main_branch = WorkshopBranch(
            workshop_id=workshop.id,
            name="Casa Central",
            address=workshop.address,
            latitude=workshop.latitude,
            longitude=workshop.longitude,
            coverage_radius_km=workshop.coverage_radius_km,
            opening_time=workshop.opening_time,
            closing_time=workshop.closing_time,
            serves_24h=workshop.serves_24h,
            max_concurrent_capacity=workshop.max_concurrent_capacity,
        )
        secondary_branch = WorkshopBranch(
            workshop_id=workshop.id,
            name="Sucursal 2",
            address=f"{AVENUES[(index + 2) % len(AVENUES)]}, {ZONES[(index + 3) % len(ZONES)]}, 4to anillo #{220 + index}",
            latitude=(workshop.latitude or Decimal("-17.78332700")) + Decimal("0.0006"),
            longitude=(workshop.longitude or Decimal("-63.18214000")) + Decimal("0.0006"),
            coverage_radius_km=max(15, workshop.coverage_radius_km - 5),
            opening_time=workshop.opening_time,
            closing_time=workshop.closing_time,
            max_concurrent_capacity=max(2, workshop.max_concurrent_capacity - 1),
        )
        seeded_branches = [main_branch, secondary_branch]
        if BRANCHES_PER_WORKSHOP >= 3:
            seeded_branches.append(
                WorkshopBranch(
                    workshop_id=workshop.id,
                    name="Punto Express",
                    address=f"{AVENUES[(index + 4) % len(AVENUES)]}, {ZONES[(index + 5) % len(ZONES)]}, radial #{320 + index}",
                    latitude=(workshop.latitude or Decimal("-17.78332700")) + Decimal("0.0014"),
                    longitude=(workshop.longitude or Decimal("-63.18214000")) - Decimal("0.0010"),
                    coverage_radius_km=max(10, workshop.coverage_radius_km - 10),
                    opening_time=time(7, 30),
                    closing_time=time(22, 0),
                    serves_24h=index % 5 == 0,
                    max_concurrent_capacity=2 + (index % 2),
                )
            )
        branches.extend(seeded_branches)
        session.add_all(seeded_branches)
        session.add(
            WorkshopAvailabilityHistory(
                workshop_id=workshop.id,
                old_state_id=None,
                new_state_id=workshop.availability_state_id,
                current_capacity=workshop.current_concurrent_capacity,
                accepts_requests=workshop.accepts_requests,
                notes="Estado operativo inicial seed",
                action_account_id=owner_account.id,
            )
        )
    await session.flush()
    return owners, workshops, branches


async def seed_admins(session: AsyncSession, roles: dict[str, Role]) -> list[Administrator]:
    admins: list[Administrator] = []
    for index in range(ADMIN_COUNT):
        first, last = name_pair(index + 120)
        account = await create_account(
            session,
            email=DEMO_ADMIN_EMAIL if index == 0 else f"admin{index + 1:02d}@{SEED_EMAIL_DOMAIN}",
            role=roles[AccountRoleName.ADMIN.value],
            phone_number=phone(index + 120),
        )
        admins.append(Administrator(account_id=account.id, first_name=first, last_name=last))
    session.add_all(admins)
    await session.flush()
    return admins


async def seed_workers(
    session: AsyncSession,
    roles: dict[str, Role],
    workshops: list[Workshop],
    branches: list[WorkshopBranch],
    specialties: list[Specialty],
    worker_statuses: dict[str, WorkerStatus],
) -> list[Worker]:
    workers: list[Worker] = []
    specialty_links: list[WorkerSpecialty] = []
    status_history: list[WorkerStatusHistory] = []
    branch_map: dict[int, list[WorkshopBranch]] = {}
    for branch in branches:
        branch_map.setdefault(branch.workshop_id, []).append(branch)

    for workshop_index, workshop in enumerate(workshops):
        workshop_branches = sorted(branch_map[workshop.id], key=lambda item: item.id)
        for offset in range(WORKERS_PER_WORKSHOP):
            idx = workshop_index * WORKERS_PER_WORKSHOP + offset
            first, last = name_pair(idx + 200)
            status_name = ["libre", "en_camino", "en_servicio"][offset % 3]
            status = worker_statuses[status_name]
            specialty = specialties[idx % len(specialties)]
            account = await create_account(
                session,
                email=DEMO_WORKER_EMAIL if idx == 0 else f"tecnico{idx + 1:02d}@{SEED_EMAIL_DOMAIN}",
                role=roles[AccountRoleName.WORKER.value],
                phone_number=phone(idx + 200),
            )
            worker = Worker(
                workshop_id=workshop.id,
                branch_id=workshop_branches[offset % len(workshop_branches)].id,
                account_id=account.id,
                operational_status_id=status.id,
                first_name=first,
                last_name=last,
                national_id=f"TEC-{7900000 + idx}",
                phone=account.phone,
                email=account.email,
                main_specialty=specialty.name,
                is_available=status_name == "libre",
                current_latitude=geo_offset("-17.79000000", idx, "0.0007"),
                current_longitude=geo_offset("-63.19000000", idx, "0.0007"),
                last_location_at=datetime.utcnow() - timedelta(minutes=idx),
                hired_on=date(2023, (idx % 12) + 1, (idx % 27) + 1),
                average_rating=Decimal("4.00") + Decimal(idx % 6) / Decimal("10"),
                total_ratings=6 + (idx % 10),
            )
            workers.append(worker)
            session.add(worker)
            await session.flush()
            specialty_links.extend(
                [
                    WorkerSpecialty(worker_id=worker.id, specialty_id=specialties[idx % len(specialties)].id, experience_level=ExperienceLevel.INTERMEDIATE),
                    WorkerSpecialty(worker_id=worker.id, specialty_id=specialties[(idx + 1) % len(specialties)].id, experience_level=ExperienceLevel.ADVANCED),
                ]
            )
            status_history.append(
                WorkerStatusHistory(
                    worker_id=worker.id,
                    old_status_id=None,
                    new_status_id=status.id,
                    changed_at=datetime.utcnow() - timedelta(days=idx % 15),
                    notes="Estado inicial seed",
                    action_account_id=account.id,
                )
            )

    session.add_all([*specialty_links, *status_history])
    await session.flush()
    return workers


async def seed_vehicles(session: AsyncSession, clients: list[User]) -> list[Vehicle]:
    vehicles: list[Vehicle] = []
    brands = list(CAR_BRANDS.keys())
    colors = ["Blanco", "Negro", "Rojo", "Azul", "Gris", "Plata"]
    vehicle_types = [VehicleType.CAR, VehicleType.PICKUP, VehicleType.MOTORCYCLE, VehicleType.TRUCK]
    for index in range(VEHICLE_COUNT):
        brand = brands[index % len(brands)]
        model = CAR_BRANDS[brand][index % len(CAR_BRANDS[brand])]
        vehicles.append(
            Vehicle(
                owner_id=clients[index % len(clients)].id,
                plate=f"{3000 + index}XYZ",
                brand=brand,
                model=model,
                year=2010 + (index % 14),
                color=colors[index % len(colors)],
                vehicle_type=vehicle_types[index % len(vehicle_types)],
            )
        )
    session.add_all(vehicles)
    await session.flush()
    return vehicles


async def seed_incidents(
    session: AsyncSession,
    clients: list[User],
    vehicles: list[Vehicle],
    owners: list[WorkshopOwner],
    workshops: list[Workshop],
    branches: list[WorkshopBranch],
    workers: list[Worker],
    catalogs: dict[str, dict[str, object] | list[Specialty]],
) -> list[Notification]:
    incidents: list[Incident] = []
    assignments: list[Assignment] = []
    worker_assignments: list[WorkerAssignmentHistory] = []
    histories: list[IncidentStatusHistory] = []
    evidences: list[Evidence] = []
    notifications: list[Notification] = []
    payments: list[Payment] = []
    workshop_ratings: list[WorkshopRating] = []
    worker_ratings: list[WorkerRating] = []
    chat_messages: list[IncidentChatMessage] = []
    notification_recipients: list[NotificationRecipient] = []
    ai_inferences: list[AIInference] = []
    status_map = catalogs["incident_statuses"]
    priority_map = catalogs["priorities"]
    incident_type_map = catalogs["incident_types"]
    payment_status = catalogs["payment_statuses"]["pagado"]
    payment_method_names = list(catalogs["payment_methods"].keys())
    incident_type_names = list(catalogs["incident_types"].keys())
    status_cycle = ["pendiente", "asignado", "tecnico_asignado", "en_camino", "trabajando", "finalizado", "finalizado", "en_camino", "pendiente"]
    priority_cycle = ["alta", "media", "baja"]
    now = datetime.utcnow()
    branch_map: dict[int, list[WorkshopBranch]] = {}
    for branch in branches:
        branch_map.setdefault(branch.workshop_id, []).append(branch)

    for index in range(INCIDENT_COUNT):
        client = clients[index % len(clients)]
        vehicle = vehicles[index % len(vehicles)]
        workshop = workshops[index % len(workshops)]
        workshop_worker_pool = [worker for worker in workers if worker.workshop_id == workshop.id]
        worker = workshop_worker_pool[index % len(workshop_worker_pool)]
        workshop_branches = branch_map[workshop.id]
        branch = workshop_branches[index % len(workshop_branches)]
        status_name = status_cycle[index % len(status_cycle)]
        manual_type = incident_type_map[incident_type_names[index % len(incident_type_names)]]
        ai_type = incident_type_map[incident_type_names[(index + 1) % len(incident_type_names)]]
        final_type = manual_type if index % 4 != 0 else ai_type
        reported_at = now - timedelta(hours=index * 3)
        distance_km = Decimal("3.20") + Decimal(index % 28) / Decimal("2")
        priority_multiplier = {"alta": Decimal("1.35"), "media": Decimal("1.15"), "baja": Decimal("1.00")}[priority_cycle[index % len(priority_cycle)]]
        base_cost = {
            "bateria": Decimal("90.00"),
            "llanta": Decimal("85.00"),
            "motor": Decimal("150.00"),
            "choque": Decimal("180.00"),
            "electrico": Decimal("125.00"),
            "cerradura": Decimal("75.00"),
            "remolque": Decimal("220.00"),
        }.get(manual_type.name, Decimal("110.00"))
        estimated_total = (
            base_cost
            + distance_km * Decimal("4.50")
            + priority_multiplier * Decimal("28.00")
            + Decimal("45.00")
        ).quantize(Decimal("0.01"))
        final_total = (estimated_total * Decimal("1.10")).quantize(Decimal("0.01"))
        incidents.append(
            Incident(
                client_id=client.id,
                vehicle_id=vehicle.id,
                assigned_workshop_id=workshop.id if status_name != "pendiente" else None,
                assigned_worker_id=worker.id if status_name in {"tecnico_asignado", "en_camino", "trabajando", "finalizado"} else None,
                assigned_branch_id=branch.id if status_name != "pendiente" else None,
                status_id=status_map[status_name].id,
                priority_id=priority_map[priority_cycle[index % len(priority_cycle)]].id,
                manual_incident_type_id=manual_type.id,
                ai_incident_type_id=ai_type.id,
                final_incident_type_id=final_type.id,
                incident_latitude=geo_offset("-17.78332700", index),
                incident_longitude=geo_offset("-63.18214000", index, "0.0010"),
                address_text=f"{AVENUES[index % len(AVENUES)]}, {ZONES[index % len(ZONES)]}, calle {120 + index}, Santa Cruz de la Sierra",
                description_text=f"El vehiculo presenta una falla de {manual_type.name}; el cliente solicita asistencia en ruta.",
                ai_confidence=Decimal("80.00") + Decimal(index % 15),
                manually_prioritized=index % 7 == 0,
                reported_at=reported_at,
                assigned_at=reported_at + timedelta(minutes=12) if status_name != "pendiente" else None,
                accepted_at=reported_at + timedelta(minutes=22) if status_name != "pendiente" else None,
                service_started_at=reported_at + timedelta(minutes=40) if status_name in {"trabajando", "finalizado"} else None,
                service_finished_at=reported_at + timedelta(hours=2, minutes=15) if status_name == "finalizado" else None,
                estimated_cost=estimated_total if status_name != "pendiente" else None,
                final_cost=final_total if status_name == "finalizado" else None,
                eta_minutes=20 + (index % 15) if status_name != "pendiente" else None,
                eta_at=reported_at + timedelta(minutes=20 + (index % 15)) if status_name != "pendiente" else None,
                eta_last_calculated_at=reported_at + timedelta(minutes=8) if status_name != "pendiente" else None,
                workshop_distance_km=distance_km if status_name != "pendiente" else None,
            )
        )
    session.add_all(incidents)
    await session.flush()

    for index, incident in enumerate(incidents):
        workshop = workshops[index % len(workshops)]
        workshop_worker_pool = [worker for worker in workers if worker.workshop_id == workshop.id]
        worker = workshop_worker_pool[index % len(workshop_worker_pool)]
        workshop_branches = branch_map[workshop.id]
        branch = workshop_branches[index % len(workshop_branches)]
        client = clients[index % len(clients)]
        owner = owners[index % len(owners)]
        status_name = status_cycle[index % len(status_cycle)]

        assignments.append(
            Assignment(
                incident_id=incident.id,
                candidate_workshop_id=workshop.id,
                assignment_score=Decimal("82.00") + Decimal(index % 14),
                used_criteria={
                    "distance_score": 35,
                    "capacity_score": 20,
                    "rating_score": 25,
                    "availability_score": 20,
                    "specialty_score": 15,
                    "required_specialty": incident.final_classification or "motor",
                    "model": "local-incident-ai",
                },
                was_selected=incident.assigned_workshop_id == workshop.id,
                was_rejected=False,
                assigned_at=incident.reported_at + timedelta(minutes=10),
            )
        )
        histories.append(
            IncidentStatusHistory(
                incident_id=incident.id,
                old_status_id=None,
                new_status_id=incident.status_id,
                action_account_id=client.account_id,
                notes="Creacion del incidente en seed",
                changed_at=incident.reported_at,
            )
        )
        evidences.extend(
            [
                Evidence(
                    incident_id=incident.id,
                    evidence_type="imagen",
                    resource_url=f"https://seed.local/incidents/{incident.id}/photo.jpg",
                    ai_analysis="Analisis visual preliminar del incidente.",
                    visual_order=1,
                    uploaded_at=incident.reported_at + timedelta(minutes=1),
                ),
                Evidence(
                    incident_id=incident.id,
                    evidence_type="audio",
                    resource_url=f"https://seed.local/incidents/{incident.id}/audio.mp3",
                    audio_transcription="El vehiculo no responde y necesito asistencia.",
                    visual_order=2,
                    uploaded_at=incident.reported_at + timedelta(minutes=2),
                ),
            ]
        )

        notification = Notification(
            incident_id=incident.id,
            notification_type="estado_cambiado",
            title=f"Actualizacion del incidente #{incident.id}",
            message=f"El caso se encuentra en estado {status_name}.",
            sent_at=incident.reported_at + timedelta(minutes=5),
        )
        session.add(notification)
        await session.flush()
        notifications.append(notification)
        notification_recipients.append(NotificationRecipient(notification_id=notification.id, account_id=client.account_id, is_read=index % 3 == 0))
        if owner:
            notification_recipients.append(NotificationRecipient(notification_id=notification.id, account_id=owner.account_id, is_read=index % 4 == 0))

        if status_name != "pendiente":
            eta_notification = Notification(
                incident_id=incident.id,
                notification_type="eta_actualizado",
                title=f"ETA del incidente #{incident.id}",
                message=f"El tecnico llegara en aproximadamente {incident.eta_minutes or 20} minutos.",
                sent_at=incident.reported_at + timedelta(minutes=18),
            )
            session.add(eta_notification)
            await session.flush()
            notifications.append(eta_notification)
            notification_recipients.append(
                NotificationRecipient(
                    notification_id=eta_notification.id,
                    account_id=client.account_id,
                    is_read=index % 2 == 0,
                )
            )

        if incident.assigned_worker_id:
            worker_assignments.append(
                WorkerAssignmentHistory(
                    incident_id=incident.id,
                    worker_id=worker.id,
                    branch_id=branch.id,
                    assigned_at=incident.assigned_at or incident.reported_at + timedelta(minutes=15),
                    reason="Asignacion automatica seed",
                    is_current=status_name != "finalizado",
                    action_account_id=owner.account_id if owner else None,
                )
            )
            if worker.account_id:
                notification_recipients.append(NotificationRecipient(notification_id=notification.id, account_id=worker.account_id, is_read=index % 5 == 0))
                chat_messages.extend(
                    [
                        IncidentChatMessage(
                            incident_id=incident.id,
                            sender_account_id=client.account_id,
                            sender_role=AccountRoleName.CLIENT.value,
                            sender_name=f"{client.first_name} {client.last_name}",
                            message_text=f"Hola, necesito apoyo con el incidente #{incident.id}.",
                            sent_at=incident.reported_at + timedelta(minutes=16),
                        ),
                        IncidentChatMessage(
                            incident_id=incident.id,
                            sender_account_id=worker.account_id,
                            sender_role=AccountRoleName.WORKER.value,
                            sender_name=f"{worker.first_name} {worker.last_name}",
                            message_text="Estoy en camino. Te mantendré informado por este chat.",
                            sent_at=incident.reported_at + timedelta(minutes=19),
                        ),
                    ]
                )
                if status_name in {"trabajando", "finalizado"}:
                    chat_messages.append(
                        IncidentChatMessage(
                            incident_id=incident.id,
                            sender_account_id=worker.account_id,
                            sender_role=AccountRoleName.WORKER.value,
                            sender_name=f"{worker.first_name} {worker.last_name}",
                            message_text="Ya llegué al punto y estoy revisando el vehículo.",
                            sent_at=incident.reported_at + timedelta(minutes=43),
                        )
                    )

        ai_inferences.append(
            AIInference(
                incident_id=incident.id,
                process_type="resumen",
                model_provider="local-incident-ai",
                model_version="v1.0-deterministic",
                input_summary=incident.description_text,
                output_summary=(
                    f"CU19: resumen sintetico del incidente {incident.id}; clasificacion "
                    f"{incident.final_incident_type.name if incident.final_incident_type else 'otro'} "
                    "a partir de texto, audio e imagenes demo."
                ),
                confidence=incident.ai_confidence,
                duration_ms=120 + index,
                is_final_result=index % 2 == 0,
            )
        )
        ai_inferences.append(
            AIInference(
                incident_id=incident.id,
                process_type="priorizacion",
                model_provider="local-incident-ai",
                model_version="v1.0-deterministic",
                input_summary=f"Prioridad base: {incident.priority.name}",
                output_summary=f"CU20: prioridad sugerida {incident.priority.name} para incidente {incident.id} por tipo, riesgo y zona.",
                confidence=Decimal("87.00"),
                duration_ms=90 + index,
                is_final_result=index % 3 == 0,
            )
        )
        ai_inferences.append(
            AIInference(
                incident_id=incident.id,
                process_type="asignacion",
                model_provider="local-incident-ai",
                model_version="v1.0-deterministic",
                input_summary=f"Especialidad {incident.final_classification or 'motor'}, distancia {incident.workshop_distance_km or distance_km} km.",
                output_summary=f"CU21: taller {workshop.trade_name} rankeado por distancia, capacidad, rating, disponibilidad y especialidad.",
                confidence=Decimal("90.00"),
                duration_ms=110 + index,
                is_final_result=incident.assigned_workshop_id == workshop.id,
            )
        )

        if incident.final_cost:
            payment_method = catalogs["payment_methods"][payment_method_names[index % len(payment_method_names)]]
            payments.append(
                Payment(
                    incident_id=incident.id,
                    client_id=incident.client_id,
                    workshop_id=incident.assigned_workshop_id or workshop.id,
                    total_amount=incident.final_cost,
                    platform_fee=(incident.final_cost * Decimal("0.10")).quantize(Decimal("0.01")),
                    workshop_amount=(incident.final_cost * Decimal("0.90")).quantize(Decimal("0.01")),
                    status_id=payment_status.id,
                    payment_method_id=payment_method.id,
                    qr_code=f"QR-SEED-{incident.id}",
                    external_transaction_id=f"TX-{incident.id:05d}",
                    requested_at=incident.reported_at + timedelta(hours=1),
                    confirmed_at=incident.reported_at + timedelta(hours=2, minutes=10),
                )
            )
            workshop_ratings.append(
                WorkshopRating(
                    incident_id=incident.id,
                    workshop_id=incident.assigned_workshop_id or workshop.id,
                    client_id=incident.client_id,
                    score=4 + (index % 2),
                    comment="Atencion rapida y ordenada.",
                    rated_at=incident.reported_at + timedelta(hours=3),
                )
            )
            worker_ratings.append(
                WorkerRating(
                    incident_id=incident.id,
                    worker_id=worker.id,
                    client_id=incident.client_id,
                    score=4 + (index % 2),
                    comment="Tecnico puntual y resolutivo.",
                    punctuality=4 + (index % 2),
                    work_quality=5,
                    customer_service=4,
                    rated_at=incident.reported_at + timedelta(hours=3, minutes=10),
                )
            )

    session.add_all([
        *assignments,
        *worker_assignments,
        *histories,
        *evidences,
        *chat_messages,
        *notification_recipients,
        *ai_inferences,
        *payments,
        *workshop_ratings,
        *worker_ratings,
    ])
    await session.flush()
    return notifications


async def seed_metrics(session: AsyncSession) -> None:
    metrics: list[DailyMetric] = []
    for index in range(10):
        current_date = date.today() - timedelta(days=index)
        metrics.append(
            DailyMetric(
                metric_date=current_date,
                total_incidents=32 + index,
                incidents_by_type={"bateria": 8 + index, "llanta": 7, "motor": 6, "electrico": 4, "remolque": 3},
                avg_assignment_seconds=Decimal("520.00") + Decimal(index * 8),
                avg_service_minutes=Decimal("72.50") + Decimal(index),
                workshop_acceptance_rate=Decimal("84.20") - Decimal(index) / Decimal("10"),
                platform_revenue=Decimal("430.00") + Decimal(index * 35),
                ai_classification_precision=Decimal("88.30") + Decimal(index) / Decimal("20"),
            )
        )
    session.add_all(metrics)
    await session.flush()


async def seed_platform_activity(
    session: AsyncSession,
    accounts: list[Account],
    admins: list[Administrator],
    notifications: list[Notification],
) -> None:
    auth_sessions: list[AuthSession] = []
    login_attempts: list[LoginAttempt] = []
    devices: list[PushDevice] = []
    deliveries: list[NotificationDelivery] = []
    admin_events: list[AdminEvent] = []
    now = datetime.utcnow()

    for index, account in enumerate(accounts[:60]):
        auth_sessions.append(
            AuthSession(
                account_id=account.id,
                channel="web" if index % 3 else "movil",
                platform="web" if index % 3 else "android",
                source_ip=f"192.168.1.{(index % 200) + 10}",
                user_agent="Seeded Browser" if index % 3 else "Seeded Mobile App",
                started_at=now - timedelta(days=index % 10, hours=index % 6),
                expires_at=now + timedelta(hours=12),
                last_refresh_at=now - timedelta(hours=index % 4),
                is_revoked=False,
            )
        )
        login_attempts.append(
            LoginAttempt(
                attempted_email=account.email,
                account_id=account.id,
                succeeded=True,
                source_ip=f"192.168.1.{(index % 200) + 10}",
                user_agent="Seeded Browser",
                channel="web",
                attempted_at=now - timedelta(days=index % 10, minutes=index),
            )
        )
        devices.append(
            PushDevice(
                account_id=account.id,
                channel="movil" if index % 2 == 0 else "web",
                platform="android" if index % 2 == 0 else "web",
                push_token=f"push-token-{account.id}",
                sns_endpoint_arn=f"arn:aws:sns:us-east-1:000000000000:endpoint/GCM/asistencia-vehicular-android/{account.id}",
                sns_application_arn="arn:aws:sns:us-east-1:000000000000:app/GCM/asistencia-vehicular-android",
                is_active=index % 7 != 0,
                registered_at=now - timedelta(days=index % 14),
                last_used_at=now - timedelta(hours=index % 12),
                last_delivery_status=["registered", "sent", "failed"][index % 3],
                last_error="Credenciales FCM expiradas" if index % 11 == 0 else None,
            )
        )

    session.add_all([*auth_sessions, *login_attempts, *devices])
    await session.flush()

    for index, notification in enumerate(notifications[:80]):
        device = devices[index % len(devices)]
        deliveries.append(
            NotificationDelivery(
                notification_id=notification.id,
                device_id=device.id,
                delivery_status=["pendiente", "enviado", "entregado", "fallido"][index % 4],
                sent_at=notification.sent_at,
                delivered_at=notification.sent_at + timedelta(minutes=2) if index % 4 in {1, 2} else None,
                error_detail="Token invalido" if index % 4 == 3 else None,
            )
        )

    for index, admin in enumerate(admins):
        admin_events.append(
            AdminEvent(
                admin_id=admin.id,
                entity="workshop",
                entity_id=index + 1,
                action="approve" if index % 2 == 0 else "review",
                notes="Evento administrativo seed",
                event_at=now - timedelta(days=index),
            )
        )

    session.add_all([*deliveries, *admin_events])
    await session.flush()


async def current_counts(session: AsyncSession) -> SeedResult:
    async def count(model: type[object]) -> int:
        return int((await session.scalar(select(func.count()).select_from(model))) or 0)

    return SeedResult(
        accounts=await count(Account),
        clients=await count(User),
        owners=await count(WorkshopOwner),
        admins=await count(Administrator),
        workshops=await count(Workshop),
        branches=await count(WorkshopBranch),
        workers=await count(Worker),
        vehicles=await count(Vehicle),
        incidents=await count(Incident),
        payments=await count(Payment),
        notifications=await count(Notification),
    )


async def run_seed(clear_existing: bool) -> SeedResult:
    if clear_existing:
        await db_session.drop_all()
    await db_session.create_all()
    async with db_session.session() as session:
        if not clear_existing and (await session.scalar(select(func.count()).select_from(Account))):
            return await current_counts(session)
        catalogs = await seed_catalogs(session)
        clients = await seed_clients(session, catalogs["roles"])
        owners, workshops, branches = await seed_owners_and_workshops(session, catalogs["roles"], catalogs["workshop_availability_states"])
        admins = await seed_admins(session, catalogs["roles"])
        workers = await seed_workers(session, catalogs["roles"], workshops, branches, catalogs["specialties"], catalogs["worker_statuses"])
        vehicles = await seed_vehicles(session, clients)
        notifications = await seed_incidents(session, clients, vehicles, owners, workshops, branches, workers, catalogs)
        await seed_metrics(session)
        all_accounts = (await session.scalars(select(Account).order_by(Account.id))).all()
        await seed_platform_activity(session, all_accounts, admins, notifications)
        await session.commit()
        return await current_counts(session)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seeder detallado para asistencia vehicular.")
    parser.add_argument("--keep-existing", action="store_true", help="Conserva datos existentes si la base ya tiene informacion.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await run_seed(clear_existing=not args.keep_existing)
    print("Seeder detallado ejecutado correctamente.")
    print(f"Cuentas: {result.accounts}")
    print(f"Clientes: {result.clients}")
    print(f"Propietarios: {result.owners}")
    print(f"Administradores: {result.admins}")
    print(f"Talleres: {result.workshops}")
    print(f"Sucursales: {result.branches}")
    print(f"Trabajadores: {result.workers}")
    print(f"Vehiculos: {result.vehicles}")
    print(f"Incidentes: {result.incidents}")
    print(f"Pagos: {result.payments}")
    print(f"Notificaciones: {result.notifications}")
    print(f"Cliente demo: {DEMO_CLIENT_EMAIL} / {DEFAULT_PASSWORD}")
    print(f"Propietario demo: {DEMO_WORKSHOP_EMAIL} / {DEFAULT_PASSWORD}")
    print(f"Tecnico demo: {DEMO_WORKER_EMAIL} / {DEFAULT_PASSWORD}")
    print(f"Admin demo: {DEMO_ADMIN_EMAIL} / {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())

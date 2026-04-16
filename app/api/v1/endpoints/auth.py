from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_account, get_db_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import (
    Account,
    AccountRole,
    AccountRoleName,
    AuthSession,
    LoginAttempt,
    Permission,
    PushDevice,
    Role,
    RolePermission,
    User,
    Workshop,
    WorkshopAvailabilityHistory,
    WorkshopAvailabilityState,
    WorkshopBranch,
    WorkshopOwner,
    WorkshopOwnerLink,
)
from app.schemas.auth import (
    ClientRegisterRequest,
    LoginRequest,
    LogoutRequest,
    TokenResponse,
    WorkshopRegisterRequest,
)
from app.schemas.user import UserSummary, WorkshopProfileResponse

router = APIRouter()


ROLE_DESCRIPTIONS = {
    AccountRoleName.CLIENT.value: "Cliente que reporta emergencias",
    AccountRoleName.WORKSHOP_OWNER.value: "Dueño o responsable principal del taller",
    AccountRoleName.WORKER.value: "Tecnico del taller",
    AccountRoleName.ADMIN.value: "Administrador de la plataforma",
}

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

WORKSHOP_AVAILABILITY_STATES = {
    "disponible": "Puede recibir nuevas solicitudes",
    "saturado": "Tiene capacidad completa",
    "cerrado": "No atiende por horario",
    "pausado": "Suspendido temporalmente",
    "inactivo": "Deshabilitado en la plataforma",
}


async def ensure_role_catalog(session: AsyncSession) -> dict[str, Role]:
    roles = (await session.scalars(select(Role))).all()
    role_map = {role.name: role for role in roles}
    missing = [name for name in ROLE_DESCRIPTIONS if name not in role_map]
    if missing:
        session.add_all([Role(name=name, description=ROLE_DESCRIPTIONS[name]) for name in missing])
        await session.flush()
        roles = (await session.scalars(select(Role))).all()
        role_map = {role.name: role for role in roles}
    return role_map


async def ensure_permission_catalog(session: AsyncSession, role_map: dict[str, Role]) -> None:
    permissions = (await session.scalars(select(Permission))).all()
    permission_map = {permission.code: permission for permission in permissions}
    missing_permissions = [
        Permission(code=code, description=description)
        for entries in PERMISSIONS_BY_ROLE.values()
        for code, description in entries
        if code not in permission_map
    ]
    if missing_permissions:
        session.add_all(missing_permissions)
        await session.flush()
        permissions = (await session.scalars(select(Permission))).all()
        permission_map = {permission.code: permission for permission in permissions}

    existing_links = {
        (link.role_id, link.permission_id)
        for link in (await session.scalars(select(RolePermission))).all()
    }
    new_links: list[RolePermission] = []
    for role_name, entries in PERMISSIONS_BY_ROLE.items():
        role = role_map[role_name]
        for code, _description in entries:
            permission = permission_map[code]
            key = (role.id, permission.id)
            if key not in existing_links:
                new_links.append(RolePermission(role_id=role.id, permission_id=permission.id))
                existing_links.add(key)
    if new_links:
        session.add_all(new_links)
        await session.flush()


async def ensure_workshop_availability_catalog(session: AsyncSession) -> dict[str, WorkshopAvailabilityState]:
    existing = (await session.scalars(select(WorkshopAvailabilityState))).all()
    state_map = {state.name: state for state in existing}
    missing = [name for name in WORKSHOP_AVAILABILITY_STATES if name not in state_map]
    if missing:
        session.add_all(
            [
                WorkshopAvailabilityState(name=name, description=WORKSHOP_AVAILABILITY_STATES[name])
                for name in missing
            ]
        )
        await session.flush()
        existing = (await session.scalars(select(WorkshopAvailabilityState))).all()
        state_map = {state.name: state for state in existing}
    return state_map


async def ensure_email_not_taken(session: AsyncSession, email: str) -> None:
    existing = await session.scalar(select(Account).where(Account.email == email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El correo ya está registrado.")


async def build_session_context(account: Account, session: AsyncSession) -> TokenResponse:
    account = await session.scalar(
        select(Account)
        .options(
            selectinload(Account.account_roles).selectinload(AccountRole.role).selectinload(Role.permissions).selectinload(RolePermission.permission),
            selectinload(Account.client_profile),
            selectinload(Account.owner_profile),
            selectinload(Account.worker_profile),
            selectinload(Account.admin_profile),
        )
        .where(Account.id == account.id)
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada.")
    role = account.primary_role
    profile_id = None
    profile_type = None
    workshop_id = None
    branch_id = None
    if role == AccountRoleName.CLIENT.value and account.client_profile:
        profile_id = account.client_profile.id
        profile_type = "client"
    elif role == AccountRoleName.WORKSHOP_OWNER.value and account.owner_profile:
        profile_id = account.owner_profile.id
        profile_type = "workshop_owner"
        owner = await session.scalar(
            select(WorkshopOwner)
            .options(selectinload(WorkshopOwner.workshop_links).selectinload(WorkshopOwnerLink.workshop).selectinload(Workshop.branches))
            .where(WorkshopOwner.id == account.owner_profile.id)
        )
        if owner and owner.workshop_links:
            primary_link = next((link for link in owner.workshop_links if link.is_primary), owner.workshop_links[0])
            workshop_id = primary_link.workshop_id
            if primary_link.workshop.branches:
                branch_id = primary_link.workshop.branches[0].id
    elif role == AccountRoleName.WORKER.value and account.worker_profile:
        profile_id = account.worker_profile.id
        profile_type = "worker"
        workshop_id = account.worker_profile.workshop_id
        branch_id = account.worker_profile.branch_id
    elif role == AccountRoleName.ADMIN.value and account.admin_profile:
        profile_id = account.admin_profile.id
        profile_type = "admin"
    active_session = await session.scalar(
        select(AuthSession).where(AuthSession.account_id == account.id).order_by(AuthSession.started_at.desc())
    )
    return TokenResponse(
        access_token=create_access_token(account.id, role or "", str(active_session.access_jti) if active_session else None),
        user_id=account.id,
        role=role or "",
        profile_id=profile_id,
        profile_type=profile_type,
        workshop_id=workshop_id,
        branch_id=branch_id,
        display_name=account.display_name,
        permissions=account.permission_codes,
        session_id=active_session.id if active_session else None,
    )


@router.post("/register/client", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
async def register_client(
    payload: ClientRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> UserSummary:
    await ensure_email_not_taken(session, payload.email)
    role_map = await ensure_role_catalog(session)
    await ensure_permission_catalog(session, role_map)
    account = Account(
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        is_verified=True,
    )
    session.add(account)
    await session.flush()
    session.add(AccountRole(account_id=account.id, role_id=role_map[AccountRoleName.CLIENT.value].id))
    user = User(
        account_id=account.id,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserSummary.model_validate(user)


@router.post("/register/workshop", response_model=WorkshopProfileResponse, status_code=status.HTTP_201_CREATED)
async def register_workshop(
    payload: WorkshopRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> WorkshopProfileResponse:
    await ensure_email_not_taken(session, payload.email)
    role_map = await ensure_role_catalog(session)
    await ensure_permission_catalog(session, role_map)
    availability_states = await ensure_workshop_availability_catalog(session)
    account = Account(
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        is_verified=True,
    )
    session.add(account)
    await session.flush()
    session.add(AccountRole(account_id=account.id, role_id=role_map[AccountRoleName.WORKSHOP_OWNER.value].id))
    owner = WorkshopOwner(
        account_id=account.id,
        first_name=payload.owner_first_name,
        last_name=payload.owner_last_name,
        national_id=payload.owner_document_id or f"AUTO-{payload.phone[-8:]}",
        phone=payload.phone,
    )
    session.add(owner)
    await session.flush()
    workshop = Workshop(
        trade_name=payload.trade_name,
        legal_name=payload.legal_name,
        tax_id=payload.tax_id,
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        coverage_radius_km=payload.coverage_radius_km,
        serves_24h=payload.serves_24h,
        max_concurrent_capacity=payload.max_concurrent_capacity,
        is_available=True,
        primary_owner_id=owner.id,
        availability_state_id=availability_states["disponible"].id,
        current_concurrent_capacity=0,
        accepts_requests=True,
    )
    session.add(workshop)
    await session.flush()
    session.add(WorkshopOwnerLink(owner_id=owner.id, workshop_id=workshop.id, is_primary=True))
    session.add(
        WorkshopAvailabilityHistory(
            workshop_id=workshop.id,
            old_state_id=None,
            new_state_id=availability_states["disponible"].id,
            current_capacity=0,
            accepts_requests=True,
            notes="Estado inicial al registrar taller",
            action_account_id=account.id,
        )
    )
    session.add(
        WorkshopBranch(
            workshop_id=workshop.id,
            name="Casa Central",
            address=payload.address,
            coverage_radius_km=payload.coverage_radius_km,
            serves_24h=payload.serves_24h,
            max_concurrent_capacity=payload.max_concurrent_capacity,
            is_active=True,
        )
    )
    await session.commit()
    workshop = await session.scalar(
        select(Workshop)
        .options(
            selectinload(Workshop.branches),
            selectinload(Workshop.owner_links).selectinload(WorkshopOwnerLink.owner).selectinload(WorkshopOwner.account),
        )
        .where(Workshop.id == workshop.id)
    )
    return WorkshopProfileResponse.model_validate(
        {
            **workshop.__dict__,
            "primary_owner": (
                {
                    "id": workshop.primary_owner.id,
                    "account_id": workshop.primary_owner.account_id,
                    "first_name": workshop.primary_owner.first_name,
                    "last_name": workshop.primary_owner.last_name,
                    "national_id": workshop.primary_owner.national_id,
                    "email": workshop.primary_owner.email,
                    "phone": workshop.primary_owner.phone,
                }
                if workshop and workshop.primary_owner
                else None
            ),
            "branches": [
                {
                    "id": branch.id,
                    "workshop_id": branch.workshop_id,
                    "name": branch.name,
                    "address": branch.address,
                    "coverage_radius_km": branch.coverage_radius_km,
                    "serves_24h": branch.serves_24h,
                    "max_concurrent_capacity": branch.max_concurrent_capacity,
                    "is_active": branch.is_active,
                }
                for branch in (workshop.branches if workshop else [])
            ],
        }
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    role_map = await ensure_role_catalog(session)
    await ensure_permission_catalog(session, role_map)
    account = await session.scalar(
        select(Account)
        .options(
            selectinload(Account.account_roles).selectinload(AccountRole.role).selectinload(Role.permissions).selectinload(RolePermission.permission),
            selectinload(Account.client_profile),
            selectinload(Account.owner_profile),
            selectinload(Account.worker_profile),
            selectinload(Account.admin_profile),
        )
        .where(Account.email == payload.email)
    )
    if not account or not verify_password(payload.password, account.password_hash):
        session.add(
            LoginAttempt(
                attempted_email=payload.email,
                account_id=account.id if account else None,
                succeeded=False,
                source_ip=x_forwarded_for,
                user_agent=user_agent,
                channel=payload.channel,
            )
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas.")
    account.last_access_at = datetime.utcnow()
    auth_session = AuthSession(
        account_id=account.id,
        channel=payload.channel,
        platform=payload.platform,
        source_ip=x_forwarded_for,
        user_agent=user_agent,
        expires_at=datetime.utcnow() + timedelta(hours=12),
    )
    session.add(
        LoginAttempt(
            attempted_email=payload.email,
            account_id=account.id,
            succeeded=True,
            source_ip=x_forwarded_for,
            user_agent=user_agent,
            channel=payload.channel,
        )
    )
    session.add(auth_session)
    await session.commit()
    return await build_session_context(account, session)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    payload: LogoutRequest | None = None,
    current_account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    active_session = await session.scalar(
        select(AuthSession)
        .where(
            AuthSession.account_id == current_account.id,
            AuthSession.is_revoked.is_(False),
            AuthSession.logged_out_at.is_(None),
        )
        .order_by(AuthSession.started_at.desc())
    )
    if active_session:
        active_session.logged_out_at = datetime.utcnow()
        active_session.is_revoked = True
        active_session.revocation_reason = payload.reason if payload else "logout"
        await session.commit()
    return {"detail": "Sesion cerrada correctamente."}

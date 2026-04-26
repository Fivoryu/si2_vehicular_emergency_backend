from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccountRoleName(str, Enum):
    CLIENT = "cliente"
    WORKSHOP_OWNER = "propietario_taller"
    WORKER = "trabajador"
    ADMIN = "admin"


class ExperienceLevel(str, Enum):
    BASIC = "basico"
    INTERMEDIATE = "intermedio"
    ADVANCED = "avanzado"


class VehicleType(str, Enum):
    CAR = "auto"
    MOTORCYCLE = "moto"
    PICKUP = "camioneta"
    TRUCK = "camion"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(150))

    account_roles: Mapped[list["AccountRole"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(150))

    roles: Mapped[list["RolePermission"]] = relationship(back_populates="permission", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), index=True)

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(back_populates="roles")


class AccountRole(Base):
    __tablename__ = "account_roles"
    __table_args__ = (UniqueConstraint("account_id", "role_id", name="uq_account_role"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account"] = relationship(back_populates="account_roles")
    role: Mapped[Role] = relationship(back_populates="account_roles")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    account_roles: Mapped[list[AccountRole]] = relationship(back_populates="account", cascade="all, delete-orphan")
    client_profile: Mapped["User | None"] = relationship(back_populates="account", uselist=False)
    owner_profile: Mapped["WorkshopOwner | None"] = relationship(back_populates="account", uselist=False)
    admin_profile: Mapped["Administrator | None"] = relationship(back_populates="account", uselist=False)
    worker_profile: Mapped["Worker | None"] = relationship(back_populates="account", uselist=False)
    notification_recipients: Mapped[list["NotificationRecipient"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    worker_status_actions: Mapped[list["WorkerStatusHistory"]] = relationship(back_populates="action_account")
    worker_assignment_actions: Mapped[list["WorkerAssignmentHistory"]] = relationship(back_populates="action_account")
    auth_sessions: Mapped[list["AuthSession"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    login_attempts: Mapped[list["LoginAttempt"]] = relationship(back_populates="account")
    push_devices: Mapped[list["PushDevice"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    workshop_availability_actions: Mapped[list["WorkshopAvailabilityHistory"]] = relationship(back_populates="action_account")

    @property
    def primary_role(self) -> str | None:
        if not self.account_roles:
            return None
        return self.account_roles[0].role.name

    @property
    def display_name(self) -> str:
        if self.owner_profile:
            return f"{self.owner_profile.first_name} {self.owner_profile.last_name}"
        if self.worker_profile:
            return f"{self.worker_profile.first_name} {self.worker_profile.last_name}"
        if self.admin_profile:
            return f"{self.admin_profile.first_name} {self.admin_profile.last_name}"
        if self.client_profile:
            return f"{self.client_profile.first_name} {self.client_profile.last_name}"
        return self.email

    @property
    def permission_codes(self) -> list[str]:
        codes: set[str] = set()
        for link in self.account_roles:
            for role_permission in link.role.permissions:
                codes.add(role_permission.permission.code)
        return sorted(codes)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    access_jti: Mapped[UUID] = mapped_column(default=uuid4, unique=True)
    refresh_jti: Mapped[UUID | None] = mapped_column(default=uuid4, unique=True)
    channel: Mapped[str] = mapped_column(String(20))
    platform: Mapped[str | None] = mapped_column(String(20))
    source_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime)
    logged_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revocation_reason: Mapped[str | None] = mapped_column(String(120))

    account: Mapped["Account"] = relationship(back_populates="auth_sessions")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attempted_email: Mapped[str] = mapped_column(String(150), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    source_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(20))
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account | None"] = relationship(back_populates="login_attempts")


class PushDevice(Base):
    __tablename__ = "push_devices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    platform: Mapped[str] = mapped_column(String(20))
    push_token: Mapped[str] = mapped_column(Text, unique=True)
    sns_endpoint_arn: Mapped[str | None] = mapped_column(Text)
    sns_application_arn: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_delivery_status: Mapped[str | None] = mapped_column(String(30))
    last_error: Mapped[str | None] = mapped_column(Text)

    account: Mapped["Account"] = relationship(back_populates="push_devices")
    notification_deliveries: Mapped[list["NotificationDelivery"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    account: Mapped[Account] = relationship(back_populates="client_profile")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="client")
    payments: Mapped[list["Payment"]] = relationship(back_populates="client")
    workshop_ratings: Mapped[list["WorkshopRating"]] = relationship(back_populates="client")
    worker_ratings: Mapped[list["WorkerRating"]] = relationship(back_populates="client")

    @property
    def email(self) -> str:
        return self.account.email

    @property
    def phone(self) -> str | None:
        return self.account.phone

    @property
    def role(self) -> str:
        return AccountRoleName.CLIENT.value


class Administrator(Base):
    __tablename__ = "administrators"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped[Account] = relationship(back_populates="admin_profile")
    events: Mapped[list["AdminEvent"]] = relationship(back_populates="admin", cascade="all, delete-orphan")


class AdminEvent(Base):
    __tablename__ = "admin_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    event_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    admin: Mapped["Administrator | None"] = relationship(back_populates="events")


class WorkshopOwner(Base):
    __tablename__ = "workshop_owners"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    national_id: Mapped[str] = mapped_column(String(20), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped[Account] = relationship(back_populates="owner_profile")
    workshop_links: Mapped[list["WorkshopOwnerLink"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def email(self) -> str:
        return self.account.email


class Workshop(Base):
    __tablename__ = "workshops"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(150), unique=True)
    phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(80))
    primary_owner_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_owners.id"))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(11, 8))
    coverage_radius_km: Mapped[int] = mapped_column(Integer, default=30)
    opening_time: Mapped[time | None] = mapped_column(Time)
    closing_time: Mapped[time | None] = mapped_column(Time)
    serves_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    max_concurrent_capacity: Mapped[int] = mapped_column(Integer, default=3)
    platform_fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_notes: Mapped[str | None] = mapped_column(Text)
    availability_state_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_availability_states.id"))
    current_concurrent_capacity: Mapped[int] = mapped_column(Integer, default=0)
    accepts_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    average_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    total_ratings: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    owner_links: Mapped[list["WorkshopOwnerLink"]] = relationship(back_populates="workshop", cascade="all, delete-orphan")
    branches: Mapped[list["WorkshopBranch"]] = relationship(back_populates="workshop", cascade="all, delete-orphan")
    workers: Mapped[list["Worker"]] = relationship(back_populates="workshop", cascade="all, delete-orphan")
    direct_primary_owner: Mapped["WorkshopOwner | None"] = relationship(foreign_keys=[primary_owner_id])
    availability_state: Mapped["WorkshopAvailabilityState | None"] = relationship(back_populates="workshops")
    availability_history: Mapped[list["WorkshopAvailabilityHistory"]] = relationship(back_populates="workshop", cascade="all, delete-orphan")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="assigned_workshop")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="candidate_workshop")
    payments: Mapped[list["Payment"]] = relationship(back_populates="workshop")
    ratings: Mapped[list["WorkshopRating"]] = relationship(back_populates="workshop")

    @property
    def primary_owner(self) -> WorkshopOwner | None:
        if not self.owner_links:
            return None
        principal_link = next((link for link in self.owner_links if link.is_primary), None)
        return principal_link.owner if principal_link else self.owner_links[0].owner


class WorkshopAvailabilityState(Base):
    __tablename__ = "workshop_availability_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(150))

    workshops: Mapped[list["Workshop"]] = relationship(back_populates="availability_state")
    old_history: Mapped[list["WorkshopAvailabilityHistory"]] = relationship(back_populates="old_state", foreign_keys="WorkshopAvailabilityHistory.old_state_id")
    new_history: Mapped[list["WorkshopAvailabilityHistory"]] = relationship(back_populates="new_state", foreign_keys="WorkshopAvailabilityHistory.new_state_id")


class WorkshopAvailabilityHistory(Base):
    __tablename__ = "workshop_availability_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id", ondelete="CASCADE"), index=True)
    old_state_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_availability_states.id"))
    new_state_id: Mapped[int] = mapped_column(ForeignKey("workshop_availability_states.id"))
    current_capacity: Mapped[int | None] = mapped_column(Integer)
    accepts_requests: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    action_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    workshop: Mapped["Workshop"] = relationship(back_populates="availability_history")
    old_state: Mapped["WorkshopAvailabilityState | None"] = relationship(back_populates="old_history", foreign_keys=[old_state_id])
    new_state: Mapped["WorkshopAvailabilityState"] = relationship(back_populates="new_history", foreign_keys=[new_state_id])
    action_account: Mapped["Account | None"] = relationship(back_populates="workshop_availability_actions")


class WorkshopOwnerLink(Base):
    __tablename__ = "workshop_owner_links"
    __table_args__ = (UniqueConstraint("owner_id", "workshop_id", name="uq_owner_workshop"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("workshop_owners.id", ondelete="CASCADE"), index=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id", ondelete="CASCADE"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[WorkshopOwner] = relationship(back_populates="workshop_links")
    workshop: Mapped[Workshop] = relationship(back_populates="owner_links")


class WorkshopBranch(Base):
    __tablename__ = "workshop_branches"
    __table_args__ = (UniqueConstraint("workshop_id", "name", name="uq_workshop_branch_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(11, 8))
    coverage_radius_km: Mapped[int] = mapped_column(Integer, default=30)
    opening_time: Mapped[time | None] = mapped_column(Time)
    closing_time: Mapped[time | None] = mapped_column(Time)
    serves_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    max_concurrent_capacity: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workshop: Mapped[Workshop] = relationship(back_populates="branches")
    workers: Mapped[list["Worker"]] = relationship(back_populates="branch")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="assigned_branch")
    worker_assignments: Mapped[list["WorkerAssignmentHistory"]] = relationship(back_populates="branch")


class WorkerStatus(Base):
    __tablename__ = "worker_statuses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(150))

    workers: Mapped[list["Worker"]] = relationship(back_populates="operational_status")
    old_history: Mapped[list["WorkerStatusHistory"]] = relationship(back_populates="old_status", foreign_keys="WorkerStatusHistory.old_status_id")
    new_history: Mapped[list["WorkerStatusHistory"]] = relationship(back_populates="new_status", foreign_keys="WorkerStatusHistory.new_status_id")


class WorkerStatusHistory(Base):
    __tablename__ = "worker_status_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    old_status_id: Mapped[int | None] = mapped_column(ForeignKey("worker_statuses.id"))
    new_status_id: Mapped[int] = mapped_column(ForeignKey("worker_statuses.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text)
    action_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    worker: Mapped["Worker"] = relationship(back_populates="status_history")
    old_status: Mapped[WorkerStatus | None] = relationship(back_populates="old_history", foreign_keys=[old_status_id])
    new_status: Mapped[WorkerStatus] = relationship(back_populates="new_history", foreign_keys=[new_status_id])
    action_account: Mapped[Account | None] = relationship(back_populates="worker_status_actions")


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_branches.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), unique=True)
    operational_status_id: Mapped[int | None] = mapped_column(ForeignKey("worker_statuses.id"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    national_id: Mapped[str] = mapped_column(String(20), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    main_specialty: Mapped[str | None] = mapped_column(String(50))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    current_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    current_longitude: Mapped[Decimal | None] = mapped_column(Numeric(11, 8))
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime)
    hired_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    average_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    total_ratings: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    account: Mapped[Account | None] = relationship(back_populates="worker_profile")
    workshop: Mapped[Workshop] = relationship(back_populates="workers")
    branch: Mapped[WorkshopBranch | None] = relationship(back_populates="workers")
    operational_status: Mapped[WorkerStatus | None] = relationship(back_populates="workers")
    specialties: Mapped[list["WorkerSpecialty"]] = relationship(back_populates="worker", cascade="all, delete-orphan")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="assigned_worker")
    ratings: Mapped[list["WorkerRating"]] = relationship(back_populates="worker")
    status_history: Mapped[list[WorkerStatusHistory]] = relationship(back_populates="worker", cascade="all, delete-orphan")
    assignment_history: Mapped[list["WorkerAssignmentHistory"]] = relationship(back_populates="worker", cascade="all, delete-orphan")


class Specialty(Base):
    __tablename__ = "specialties"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    workers: Mapped[list["WorkerSpecialty"]] = relationship(back_populates="specialty", cascade="all, delete-orphan")


class WorkerSpecialty(Base):
    __tablename__ = "worker_specialties"
    __table_args__ = (UniqueConstraint("worker_id", "specialty_id", name="uq_worker_specialty"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"))
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id", ondelete="CASCADE"))
    experience_level: Mapped[ExperienceLevel] = mapped_column(SqlEnum(ExperienceLevel), default=ExperienceLevel.INTERMEDIATE)

    worker: Mapped[Worker] = relationship(back_populates="specialties")
    specialty: Mapped[Specialty] = relationship(back_populates="workers")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plate: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    year: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(30))
    vehicle_type: Mapped[VehicleType | None] = mapped_column(SqlEnum(VehicleType))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User] = relationship(back_populates="vehicles")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="vehicle")


from app.models.emergency import (  # noqa: E402
    Assignment,
    Incident,
    NotificationDelivery,
    NotificationRecipient,
    Payment,
    WorkerAssignmentHistory,
    WorkerRating,
    WorkshopRating,
)

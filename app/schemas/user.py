from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None
    role: str
    is_active: bool
    created_at: datetime


class VehicleCreate(BaseModel):
    owner_id: int
    plate: str = Field(min_length=5, max_length=20)
    brand: str = Field(min_length=2, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    year: int | None = Field(default=None, ge=1950, le=2100)
    color: str | None = Field(default=None, max_length=30)
    vehicle_type: str | None = Field(default=None)


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    plate: str
    brand: str
    model: str
    year: int | None
    color: str | None
    vehicle_type: str | None
    registered_at: datetime


class WorkshopOwnerSummary(BaseModel):
    id: int
    account_id: int
    first_name: str
    last_name: str
    national_id: str
    email: EmailStr
    phone: str | None


class BranchSummary(BaseModel):
    id: int
    workshop_id: int
    name: str
    address: str
    coverage_radius_km: int
    serves_24h: bool
    max_concurrent_capacity: int
    is_active: bool


class WorkerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int | None
    branch_id: int | None
    first_name: str
    last_name: str
    national_id: str
    phone: str | None
    email: str | None
    main_specialty: str | None
    operational_status: str | None
    is_available: bool
    average_rating: Decimal


class WorkshopProfileResponse(BaseModel):
    id: int
    trade_name: str
    legal_name: str | None
    tax_id: str | None
    email: EmailStr
    phone: str
    address: str
    city: str
    coverage_radius_km: int
    serves_24h: bool
    max_concurrent_capacity: int
    is_available: bool
    availability_state: str | None = None
    current_concurrent_capacity: int = 0
    accepts_requests: bool = True
    is_admin_approved: bool = False
    approved_at: datetime | None = None
    approval_notes: str | None = None
    average_rating: Decimal
    total_ratings: int
    primary_owner: WorkshopOwnerSummary | None = None
    branches: list[BranchSummary] = Field(default_factory=list)


class WorkshopAvailabilityUpdate(BaseModel):
    is_available: bool
    max_concurrent_capacity: int = Field(ge=1, le=100)
    availability_state: str | None = None
    current_concurrent_capacity: int | None = Field(default=None, ge=0, le=100)
    accepts_requests: bool | None = None
    notes: str | None = None


class WorkshopDashboardMetrics(BaseModel):
    active_incidents: int
    pending_incidents: int
    completed_today: int
    active_workers: int
    available_workers: int
    total_branches: int
    average_rating: Decimal
    acceptance_rate: Decimal
    recent_revenue: Decimal
    availability_state: str | None = None
    current_capacity: int = 0
    accepts_requests: bool = True


class WorkshopCatalogSummary(BaseModel):
    specialties: list[str]
    workers: list[WorkerSummary]
    branches: list[BranchSummary]
    cities: list[str]


class DailyMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metric_date: date
    total_incidents: int
    incidents_by_type: dict | None
    avg_assignment_seconds: Decimal | None
    avg_service_minutes: Decimal | None
    workshop_acceptance_rate: Decimal | None
    platform_revenue: Decimal | None


class WorkerDashboardResponse(BaseModel):
    worker_id: int
    account_id: int | None
    workshop_id: int
    workshop_name: str
    branch: BranchSummary | None
    operational_status: str | None
    is_available: bool
    average_rating: Decimal
    assigned_incidents: list[dict]
    unread_notifications: int
    permissions: list[str] = Field(default_factory=list)


class AdminDashboardMetrics(BaseModel):
    total_accounts: int
    total_clients: int
    total_workshops: int
    total_branches: int
    total_workers: int
    total_incidents: int
    active_incidents: int
    pending_incidents: int
    platform_revenue: Decimal
    active_sessions: int = 0
    workshops: list[dict]
    recent_incidents: list[dict]
    admin_events: list[dict] = Field(default_factory=list)


class ClientDashboardSummary(BaseModel):
    client_id: int
    account_id: int
    full_name: str
    email: EmailStr
    phone: str | None
    vehicles: list[VehicleResponse]
    incidents: list[dict]
    payments: list[dict]
    unread_notifications: int
    permissions: list[str] = Field(default_factory=list)


class DashboardBootstrapResponse(BaseModel):
    role: str
    profile_id: int | None
    profile_type: str | None
    workshop_id: int | None = None
    branch_id: int | None = None
    display_name: str | None = None
    permissions: list[str] = Field(default_factory=list)
    worker_dashboard: WorkerDashboardResponse | None = None
    admin_dashboard: AdminDashboardMetrics | None = None
    client_dashboard: ClientDashboardSummary | None = None

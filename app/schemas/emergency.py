from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EmergencyCreate(BaseModel):
    client_id: int
    vehicle_id: int
    incident_latitude: Decimal
    incident_longitude: Decimal
    address_text: str | None = None
    description_text: str | None = None
    manual_incident_type: str | None = None
    priority_name: str = Field(default="media")
    offered_price: Decimal | None = Field(default=None, gt=0)


class EvidenceCreate(BaseModel):
    evidence_type: str
    resource_url: str
    audio_transcription: str | None = None
    ai_analysis: str | None = None
    visual_order: int = 0


class EmergencyDecision(BaseModel):
    workshop_id: int
    accepted: bool
    rejection_reason: str | None = None


class EmergencyStatusUpdate(BaseModel):
    status_name: str
    action_user: str | None = None
    notes: str | None = None
    worker_id: int | None = None


class TechnicianOfferItem(BaseModel):
    worker_id: int
    worker_name: str
    specialty: str | None
    rating: Decimal
    distance_km: Decimal | None
    eta_minutes: int | None
    suggested_price: Decimal
    worker_offer: Decimal
    status: str | None


class TechnicianSelect(BaseModel):
    worker_id: int
    agreed_price: Decimal | None = Field(default=None, gt=0)


class WorkerLocationUpdate(BaseModel):
    latitude: Decimal
    longitude: Decimal


class TrackingResponse(BaseModel):
    incident_id: int
    status: str
    eta_minutes: int | None = None
    eta_at: datetime | None = None
    incident_coordinates: dict
    worker: dict | None = None
    workshop: dict | None = None


class ChatMessageCreate(BaseModel):
    message_text: str = Field(min_length=1, max_length=1000)


class ChatMessageResponse(BaseModel):
    id: int
    incident_id: int
    sender_account_id: int
    sender_role: str
    sender_name: str
    message_text: str
    sent_at: datetime


class ServiceRatingCreate(BaseModel):
    workshop_score: int = Field(ge=1, le=5)
    worker_score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)
    punctuality: int | None = Field(default=None, ge=1, le=5)
    work_quality: int | None = Field(default=None, ge=1, le=5)
    customer_service: int | None = Field(default=None, ge=1, le=5)


class ServiceRatingResponse(BaseModel):
    incident_id: int
    workshop_score: int
    worker_score: int
    comment: str | None = None
    rated_at: datetime


class PaymentCreate(BaseModel):
    total_amount: Decimal = Field(gt=0)
    payment_method: str = Field(min_length=2, max_length=30)
    external_transaction_id: str | None = Field(default=None, max_length=100)


class PaymentResponse(BaseModel):
    id: int
    incident_id: int
    total_amount: Decimal
    platform_fee: Decimal
    workshop_amount: Decimal
    status: str
    payment_method: str | None
    requested_at: datetime
    confirmed_at: datetime | None


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    evidence_type: str
    resource_url: str
    audio_transcription: str | None
    ai_analysis: str | None
    visual_order: int
    uploaded_at: datetime


class IncidentListItem(BaseModel):
    id: int
    client_name: str
    client_phone: str
    vehicle_label: str
    plate: str
    branch_name: str | None = None
    city: str | None
    address_text: str | None
    manual_incident_type: str | None
    final_classification: str | None
    priority: str
    status: str
    estimated_cost: Decimal | None
    final_cost: Decimal | None
    eta_minutes: int | None = None
    workshop_distance_km: Decimal | None = None
    reported_at: datetime
    assigned_worker_name: str | None
    evidence_count: int


class IncidentDetailResponse(BaseModel):
    id: int
    client_name: str
    client_phone: str
    vehicle: dict
    workshop: dict | None
    worker: dict | None
    branch: dict | None
    status: str
    priority: str
    description_text: str | None
    address_text: str | None
    coordinates: dict
    manual_incident_type: str | None
    ai_incident_type: str | None
    ai_confidence: Decimal | None
    final_classification: str | None
    estimated_cost: Decimal | None
    final_cost: Decimal | None
    eta_minutes: int | None = None
    eta_at: datetime | None = None
    eta_last_calculated_at: datetime | None = None
    workshop_distance_km: Decimal | None = None
    payment_status: str | None
    payment_summary: dict | None
    payment_method: str | None = None
    evidences: list[EvidenceResponse] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    assignments: list[dict] = Field(default_factory=list)
    worker_assignment_history: list[dict] = Field(default_factory=list)
    notifications: list[dict] = Field(default_factory=list)
    ai_inferences: list[dict] = Field(default_factory=list)

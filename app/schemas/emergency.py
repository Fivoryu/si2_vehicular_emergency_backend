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

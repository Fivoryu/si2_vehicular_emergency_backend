from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IncidentStatus(Base):
    __tablename__ = "incident_statuses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    visual_order: Mapped[int] = mapped_column(Integer)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="status")
    new_history: Mapped[list["IncidentStatusHistory"]] = relationship(back_populates="new_status", foreign_keys="IncidentStatusHistory.new_status_id")
    old_history: Mapped[list["IncidentStatusHistory"]] = relationship(back_populates="old_status", foreign_keys="IncidentStatusHistory.old_status_id")


class Priority(Base):
    __tablename__ = "priorities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)
    level: Mapped[int] = mapped_column(Integer)
    max_response_minutes: Mapped[int | None] = mapped_column(Integer)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="priority")


class IncidentType(Base):
    __tablename__ = "incident_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    manual_incidents: Mapped[list["Incident"]] = relationship(back_populates="manual_incident_type", foreign_keys="Incident.manual_incident_type_id")
    ai_incidents: Mapped[list["Incident"]] = relationship(back_populates="ai_incident_type", foreign_keys="Incident.ai_incident_type_id")
    final_incidents: Mapped[list["Incident"]] = relationship(back_populates="final_incident_type", foreign_keys="Incident.final_incident_type_id")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    assigned_workshop_id: Mapped[int | None] = mapped_column(ForeignKey("workshops.id"))
    assigned_worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"))
    assigned_branch_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_branches.id"))
    status_id: Mapped[int] = mapped_column(ForeignKey("incident_statuses.id"))
    priority_id: Mapped[int] = mapped_column(ForeignKey("priorities.id"))
    manual_incident_type_id: Mapped[int | None] = mapped_column(ForeignKey("incident_types.id"))
    ai_incident_type_id: Mapped[int | None] = mapped_column(ForeignKey("incident_types.id"))
    final_incident_type_id: Mapped[int | None] = mapped_column(ForeignKey("incident_types.id"))
    incident_latitude: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    incident_longitude: Mapped[Decimal] = mapped_column(Numeric(11, 8))
    address_text: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    manually_prioritized: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    service_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    service_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    eta_minutes: Mapped[int | None] = mapped_column(Integer)
    eta_at: Mapped[datetime | None] = mapped_column(DateTime)
    eta_last_calculated_at: Mapped[datetime | None] = mapped_column(DateTime)
    workshop_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    client: Mapped["User"] = relationship(back_populates="incidents")
    vehicle: Mapped["Vehicle"] = relationship(back_populates="incidents")
    assigned_workshop: Mapped["Workshop | None"] = relationship(back_populates="incidents")
    assigned_worker: Mapped["Worker | None"] = relationship(back_populates="incidents")
    assigned_branch: Mapped["WorkshopBranch | None"] = relationship(back_populates="incidents")
    status: Mapped[IncidentStatus] = relationship(back_populates="incidents")
    priority: Mapped[Priority] = relationship(back_populates="incidents")
    manual_incident_type: Mapped[IncidentType | None] = relationship(back_populates="manual_incidents", foreign_keys=[manual_incident_type_id])
    ai_incident_type: Mapped[IncidentType | None] = relationship(back_populates="ai_incidents", foreign_keys=[ai_incident_type_id])
    final_incident_type: Mapped[IncidentType | None] = relationship(back_populates="final_incidents", foreign_keys=[final_incident_type_id])
    evidences: Mapped[list["Evidence"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    worker_assignments: Mapped[list["WorkerAssignmentHistory"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    history: Mapped[list["IncidentStatusHistory"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    workshop_rating: Mapped["WorkshopRating | None"] = relationship(back_populates="incident", uselist=False)
    worker_rating: Mapped["WorkerRating | None"] = relationship(back_populates="incident", uselist=False)
    chat_messages: Mapped[list["IncidentChatMessage"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    ai_inferences: Mapped[list["AIInference"]] = relationship(back_populates="incident", cascade="all, delete-orphan")

    @property
    def manual_incident_type_name(self) -> str | None:
        return self.manual_incident_type.name if self.manual_incident_type else None

    @property
    def ai_incident_type_name(self) -> str | None:
        return self.ai_incident_type.name if self.ai_incident_type else None

    @property
    def final_classification(self) -> str | None:
        return self.final_incident_type.name if self.final_incident_type else None


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(20))
    resource_url: Mapped[str] = mapped_column(Text)
    audio_transcription: Mapped[str | None] = mapped_column(Text)
    ai_analysis: Mapped[str | None] = mapped_column(Text)
    visual_order: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="evidences")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    candidate_workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"))
    assignment_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    used_criteria: Mapped[dict | None] = mapped_column(JSONB)
    was_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    was_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[Incident] = relationship(back_populates="assignments")
    candidate_workshop: Mapped["Workshop"] = relationship(back_populates="assignments")


class WorkerAssignmentHistory(Base):
    __tablename__ = "worker_assignment_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_branches.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    action_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    incident: Mapped[Incident] = relationship(back_populates="worker_assignments")
    worker: Mapped["Worker"] = relationship(back_populates="assignment_history")
    branch: Mapped["WorkshopBranch | None"] = relationship(back_populates="worker_assignments")
    action_account: Mapped["Account | None"] = relationship(back_populates="worker_assignment_actions")


class IncidentStatusHistory(Base):
    __tablename__ = "incident_status_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    old_status_id: Mapped[int | None] = mapped_column(ForeignKey("incident_statuses.id"))
    new_status_id: Mapped[int] = mapped_column(ForeignKey("incident_statuses.id"))
    action_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="history")
    old_status: Mapped[IncidentStatus | None] = relationship(back_populates="old_history", foreign_keys=[old_status_id])
    new_status: Mapped[IncidentStatus] = relationship(back_populates="new_history", foreign_keys=[new_status_id])


class PaymentStatus(Base):
    __tablename__ = "payment_statuses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)

    payments: Mapped[list["Payment"]] = relationship(back_populates="status")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    payments: Mapped[list["Payment"]] = relationship(back_populates="payment_method")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    workshop_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status_id: Mapped[int] = mapped_column(ForeignKey("payment_statuses.id"))
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    qr_code: Mapped[str | None] = mapped_column(Text)
    external_transaction_id: Mapped[str | None] = mapped_column(String(100))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="payments")
    client: Mapped["User"] = relationship(back_populates="payments")
    workshop: Mapped["Workshop"] = relationship(back_populates="payments")
    status: Mapped[PaymentStatus] = relationship(back_populates="payments")
    payment_method: Mapped[PaymentMethod | None] = relationship(back_populates="payments")


class WorkshopRating(Base):
    __tablename__ = "workshop_ratings"
    __table_args__ = (UniqueConstraint("incident_id", name="uq_workshop_rating_incident"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    rated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="workshop_rating")
    workshop: Mapped["Workshop"] = relationship(back_populates="ratings")
    client: Mapped["User"] = relationship(back_populates="workshop_ratings")


class WorkerRating(Base):
    __tablename__ = "worker_ratings"
    __table_args__ = (UniqueConstraint("incident_id", name="uq_worker_rating_incident"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    punctuality: Mapped[int | None] = mapped_column(Integer)
    work_quality: Mapped[int | None] = mapped_column(Integer)
    customer_service: Mapped[int | None] = mapped_column(Integer)
    rated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="worker_rating")
    worker: Mapped["Worker"] = relationship(back_populates="ratings")
    client: Mapped["User"] = relationship(back_populates="worker_ratings")


class IncidentChatMessage(Base):
    __tablename__ = "incident_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    sender_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    sender_role: Mapped[str] = mapped_column(String(30))
    sender_name: Mapped[str] = mapped_column(String(150))
    message_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident] = relationship(back_populates="chat_messages")
    sender: Mapped["Account"] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    notification_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped[Incident | None] = relationship(back_populates="notifications")
    recipients: Mapped[list["NotificationRecipient"]] = relationship(back_populates="notification", cascade="all, delete-orphan")
    deliveries: Mapped[list["NotificationDelivery"]] = relationship(back_populates="notification", cascade="all, delete-orphan")


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"
    __table_args__ = (UniqueConstraint("notification_id", "account_id", name="uq_notification_account"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    notification: Mapped[Notification] = relationship(back_populates="recipients")
    account: Mapped["Account"] = relationship(back_populates="notification_recipients")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("push_devices.id", ondelete="CASCADE"), index=True)
    delivery_status: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_detail: Mapped[str | None] = mapped_column(Text)

    notification: Mapped[Notification] = relationship(back_populates="deliveries")
    device: Mapped["PushDevice"] = relationship(back_populates="notification_deliveries")


class AIInference(Base):
    __tablename__ = "ai_inferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    process_type: Mapped[str] = mapped_column(String(30))
    model_provider: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(40))
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_final_result: Mapped[bool] = mapped_column(Boolean, default=False)

    incident: Mapped[Incident] = relationship(back_populates="ai_inferences")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    affected_table: Mapped[str | None] = mapped_column(String(100))
    affected_record_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str | None] = mapped_column(String(20))
    previous_data: Mapped[dict | None] = mapped_column(JSONB)
    new_data: Mapped[dict | None] = mapped_column(JSONB)
    action_user: Mapped[str | None] = mapped_column(String(100))
    source_ip: Mapped[str | None] = mapped_column(String(45))
    action_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, unique=True)
    total_incidents: Mapped[int] = mapped_column(Integer, default=0)
    incidents_by_type: Mapped[dict | None] = mapped_column(JSONB)
    avg_assignment_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    avg_service_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    workshop_acceptance_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    platform_revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ai_classification_precision: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


from app.models.user import Account, PushDevice, User, Vehicle, Worker, Workshop, WorkshopBranch  # noqa: E402

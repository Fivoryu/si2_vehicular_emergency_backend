from datetime import datetime

from pydantic import BaseModel, Field


class PushDeviceRegisterRequest(BaseModel):
    push_token: str = Field(min_length=10)
    channel: str = Field(default="fcm", max_length=20)
    platform: str = Field(default="android", max_length=20)


class PushDeviceUnregisterRequest(BaseModel):
    push_token: str = Field(min_length=10)


class PushDeviceResponse(BaseModel):
    id: int
    channel: str
    platform: str
    push_token: str
    sns_endpoint_arn: str | None = None
    is_active: bool
    registered_at: datetime
    last_used_at: datetime | None = None


class NotificationListItem(BaseModel):
    id: int
    type: str
    title: str
    message: str
    incident_id: int | None = None
    is_read: bool
    sent_at: datetime

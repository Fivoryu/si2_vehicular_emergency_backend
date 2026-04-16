from pydantic import BaseModel, EmailStr, Field


class ClientRegisterRequest(BaseModel):
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=6, max_length=64)


class WorkshopRegisterRequest(BaseModel):
    owner_first_name: str = Field(min_length=2, max_length=100)
    owner_last_name: str = Field(min_length=2, max_length=100)
    owner_document_id: str | None = Field(default=None, max_length=20)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    trade_name: str = Field(min_length=3, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=50)
    address: str = Field(min_length=5)
    city: str = Field(min_length=2, max_length=80)
    coverage_radius_km: int = Field(default=30, ge=1, le=300)
    serves_24h: bool = False
    max_concurrent_capacity: int = Field(default=3, ge=1, le=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=64)
    channel: str = Field(default="web", max_length=20)
    platform: str | None = Field(default="web", max_length=20)


class LogoutRequest(BaseModel):
    reason: str | None = Field(default="logout", max_length=120)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    profile_id: int | None = None
    profile_type: str | None = None
    workshop_id: int | None = None
    branch_id: int | None = None
    display_name: str | None = None
    permissions: list[str] = Field(default_factory=list)
    session_id: int | None = None

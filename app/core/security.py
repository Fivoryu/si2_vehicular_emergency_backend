import base64
import hashlib
import hmac

from app.core.config import settings


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def create_access_token(user_id: int, role: str, session_jti: str | None = None) -> str:
    payload = f"{user_id}:{role}:{settings.app_env}"
    if session_jti:
        payload = f"{payload}:{session_jti}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")

import base64
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Callable
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import db_session
from app.models.user import Account, AccountRole, AccountRoleName, AuthSession, Role, RolePermission


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with db_session.session() as session:
        yield session


DatabaseSession = Depends(get_db_session)


def decode_access_token(token: str) -> tuple[int, str, str, str | None]:
    try:
        missing_padding = len(token) % 4
        if missing_padding:
            token += '=' * (4 - missing_padding)
        decoded = base64.urlsafe_b64decode(token.encode('utf-8')).decode('utf-8')
        parts = decoded.split(':')
        if len(parts) == 3:
            user_id_text, role, app_env = parts
            return int(user_id_text), role, app_env, None
        user_id_text, role, app_env, session_jti = parts[0], parts[1], parts[2], parts[3]
        return int(user_id_text), role, app_env, session_jti
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token invalido.') from None


async def get_current_account(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> Account:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Falta el token de acceso.')
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Formato de token invalido.')
    account_id, token_role, _app_env, session_jti = decode_access_token(token)
    account = await session.scalar(
        select(Account)
        .options(
            selectinload(Account.account_roles)
            .selectinload(AccountRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
        .where(Account.id == account_id)
    )
    if not account or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Usuario no autorizado.')
    if session_jti:
        try:
            access_uuid = UUID(session_jti)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Sesion no valida o cerrada.') from exc
        auth_session = await session.scalar(select(AuthSession).where(AuthSession.access_jti == access_uuid))
        if not auth_session or auth_session.account_id != account_id or auth_session.is_revoked or auth_session.logged_out_at:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Sesion no valida o cerrada.')
    primary_role = account.primary_role
    if primary_role != token_role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token no coincide con el rol del usuario.')
    account.last_access_at = datetime.utcnow()
    await session.commit()
    return account


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> Account:
    return await get_current_account(authorization=authorization, session=session)


def require_roles(*allowed_roles: AccountRoleName) -> Callable:
    allowed = {role.value for role in allowed_roles}

    async def role_dependency(current_user: Account = Depends(get_current_account)) -> Account:
        if current_user.primary_role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='No tienes permisos para este recurso.')
        return current_user

    return role_dependency

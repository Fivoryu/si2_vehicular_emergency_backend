from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db_session
from app.models.emergency import Notification, NotificationRecipient
from app.models.user import Account, PushDevice
from app.schemas.notification import (
    NotificationListItem,
    PushDeviceRegisterRequest,
    PushDeviceResponse,
    PushDeviceUnregisterRequest,
)
from app.services.aws import aws_service
from app.services.notification_dispatcher import ensure_device_endpoint

router = APIRouter()


@router.get("", response_model=list[NotificationListItem])
async def list_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(get_current_account),
) -> list[NotificationListItem]:
    result = await session.execute(
        select(NotificationRecipient, Notification)
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .where(NotificationRecipient.account_id == current_account.id)
        .order_by(Notification.sent_at.desc(), Notification.id.desc())
    )

    return [
        NotificationListItem(
            id=notification.id,
            type=notification.notification_type,
            title=notification.title,
            message=notification.message,
            incident_id=notification.incident_id,
            is_read=recipient.is_read,
            sent_at=notification.sent_at,
        )
        for recipient, notification in result.all()
    ]


@router.patch("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_notification_as_read(
    notification_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(get_current_account),
) -> dict[str, str]:
    recipient = await session.scalar(
        select(NotificationRecipient)
        .where(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.account_id == current_account.id,
        )
    )

    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificacion no encontrada.",
        )

    if not recipient.is_read:
        recipient.is_read = True
        await session.commit()

    return {"detail": "Notificacion marcada como leida."}


@router.post("/devices/register", response_model=PushDeviceResponse, status_code=status.HTTP_200_OK)
async def register_push_device(
    payload: PushDeviceRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(get_current_account),
) -> PushDeviceResponse:
    device = await session.scalar(select(PushDevice).where(PushDevice.push_token == payload.push_token))

    if device:
        device.account_id = current_account.id
        device.channel = payload.channel
        device.platform = payload.platform
        device.is_active = True
        device.last_used_at = datetime.utcnow()
    else:
        device = PushDevice(
            account_id=current_account.id,
            channel=payload.channel,
            platform=payload.platform,
            push_token=payload.push_token,
            is_active=True,
            last_used_at=datetime.utcnow(),
        )
        session.add(device)

    try:
        await ensure_device_endpoint(device, current_account, session)
    except Exception as error:
        device.last_delivery_status = "registration_failed"
        device.last_error = str(error)

    await session.commit()
    await session.refresh(device)

    return PushDeviceResponse(
        id=device.id,
        channel=device.channel,
        platform=device.platform,
        push_token=device.push_token,
        sns_endpoint_arn=device.sns_endpoint_arn,
        is_active=device.is_active,
        registered_at=device.registered_at,
        last_used_at=device.last_used_at,
    )


@router.post("/devices/unregister", status_code=status.HTTP_200_OK)
async def unregister_push_device(
    payload: PushDeviceUnregisterRequest,
    session: AsyncSession = Depends(get_db_session),
    current_account: Account = Depends(get_current_account),
) -> dict[str, str]:
    device = await session.scalar(
        select(PushDevice).where(
            PushDevice.push_token == payload.push_token,
            PushDevice.account_id == current_account.id,
        )
    )

    if device:
        device.is_active = False
        device.last_used_at = datetime.utcnow()
        if device.sns_endpoint_arn and aws_service.push_enabled():
            try:
                aws_service.disable_platform_endpoint(device.sns_endpoint_arn)
            except Exception as error:
                device.last_error = str(error)
        await session.commit()

    return {"detail": "Dispositivo desregistrado correctamente."}

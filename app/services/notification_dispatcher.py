from __future__ import annotations

from datetime import datetime

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.emergency import Notification, NotificationDelivery, NotificationRecipient
from app.models.user import Account, PushDevice
from app.services.aws import aws_service


async def ensure_device_endpoint(device: PushDevice, account: Account | None, session: AsyncSession) -> PushDevice:
    if not aws_service.push_enabled():
        return device

    custom_user_data = str(account.id) if account else None
    endpoint_arn = device.sns_endpoint_arn

    try:
        if endpoint_arn:
            aws_service.update_platform_endpoint(
                endpoint_arn=endpoint_arn,
                push_token=device.push_token,
                custom_user_data=custom_user_data,
            )
        else:
            endpoint_arn = aws_service.ensure_platform_endpoint(
                push_token=device.push_token,
                custom_user_data=custom_user_data,
            )
            device.sns_endpoint_arn = endpoint_arn
        device.sns_application_arn = device.sns_application_arn or settings.aws_sns_platform_application_arn
        device.last_error = None
    except (ClientError, BotoCoreError) as error:
        device.last_error = str(error)
        raise

    device.last_used_at = datetime.utcnow()
    await session.flush()
    return device


async def create_notification(
    *,
    session: AsyncSession,
    account_ids: list[int],
    title: str,
    message: str,
    notification_type: str,
    incident_id: int | None = None,
    extra_data: dict[str, str] | None = None,
) -> Notification:
    unique_account_ids = sorted(set(account_ids))
    notification = Notification(
        incident_id=incident_id,
        notification_type=notification_type,
        title=title,
        message=message,
    )
    session.add(notification)
    await session.flush()

    if unique_account_ids:
        session.add_all(
            [
                NotificationRecipient(notification_id=notification.id, account_id=account_id)
                for account_id in unique_account_ids
            ]
        )
        await session.flush()

    if not unique_account_ids:
        return notification

    devices = (
        await session.scalars(
            select(PushDevice).where(
                PushDevice.account_id.in_(unique_account_ids),
                PushDevice.is_active.is_(True),
            )
        )
    ).all()
    accounts_by_id = {
        account.id: account
        for account in (
            await session.scalars(select(Account).where(Account.id.in_(unique_account_ids)))
        ).all()
    }

    delivery_data = {
        "notification_id": str(notification.id),
        "type": notification_type,
    }
    if incident_id is not None:
        delivery_data["incident_id"] = str(incident_id)
    if extra_data:
        delivery_data.update({key: str(value) for key, value in extra_data.items()})

    for device in devices:
        try:
            await ensure_device_endpoint(device, accounts_by_id.get(device.account_id), session)
            if not device.sns_endpoint_arn:
                raise RuntimeError("SNS endpoint no disponible para el dispositivo.")
            aws_service.publish_to_endpoint(
                endpoint_arn=device.sns_endpoint_arn,
                title=title,
                message=message,
                data=delivery_data,
            )
            device.last_delivery_status = "sent"
            device.last_error = None
            session.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    device_id=device.id,
                    delivery_status="sent",
                    sent_at=datetime.utcnow(),
                )
            )
        except Exception as error:
            device.last_delivery_status = "failed"
            device.last_error = str(error)
            session.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    device_id=device.id,
                    delivery_status="failed",
                    sent_at=datetime.utcnow(),
                    error_detail=str(error),
                )
            )

    await session.flush()
    return notification

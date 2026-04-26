import json

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


class AWSService:
    def __init__(self) -> None:
        self.region = settings.aws_region
        self.bucket_name = settings.aws_s3_bucket
        self.environment_name = settings.app_env
        session = boto3.session.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        client_args = {
            "config": Config(region_name=settings.aws_region),
        }
        if settings.aws_endpoint_url:
            client_args["endpoint_url"] = settings.aws_endpoint_url

        self.s3 = session.client("s3", **client_args)
        self.sqs = session.client("sqs", **client_args)
        self.sns = session.client("sns", **client_args)

    def connections_summary(self) -> dict[str, str]:
        return {
            "region": self.region,
            "bucket": self.bucket_name,
            "queue_url": settings.aws_sqs_queue_url,
            "topic_arn": settings.aws_sns_topic_arn,
        }

    def push_enabled(self) -> bool:
        return settings.aws_push_enabled and bool(settings.aws_sns_platform_application_arn)

    def ensure_platform_endpoint(self, push_token: str, custom_user_data: str | None = None) -> str | None:
        if not self.push_enabled():
            return None
        try:
            response = self.sns.create_platform_endpoint(
                PlatformApplicationArn=settings.aws_sns_platform_application_arn,
                Token=push_token,
                CustomUserData=custom_user_data or "",
            )
            return response.get("EndpointArn")
        except (ClientError, BotoCoreError) as error:
            error_code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if error_code == "InvalidParameter" and "Endpoint" in str(error):
                marker = "Endpoint "
                end_marker = " already exists"
                message = str(error)
                if marker in message and end_marker in message:
                    return message.split(marker, 1)[1].split(end_marker, 1)[0]
            raise

    def update_platform_endpoint(self, endpoint_arn: str, push_token: str, custom_user_data: str | None = None) -> None:
        self.sns.set_endpoint_attributes(
            EndpointArn=endpoint_arn,
            Attributes={
                "Token": push_token,
                "Enabled": "true",
                "CustomUserData": custom_user_data or "",
            },
        )

    def disable_platform_endpoint(self, endpoint_arn: str) -> None:
        self.sns.set_endpoint_attributes(
            EndpointArn=endpoint_arn,
            Attributes={
                "Enabled": "false",
            },
        )

    def publish_to_endpoint(
        self,
        endpoint_arn: str,
        title: str,
        message: str,
        data: dict[str, str] | None = None,
    ) -> str:
        payload = {
            "default": message,
            "GCM": self._build_gcm_payload(title=title, message=message, data=data or {}),
        }
        response = self.sns.publish(
            TargetArn=endpoint_arn,
            MessageStructure="json",
            Message=json.dumps(payload),
        )
        return response["MessageId"]

    def _build_gcm_payload(self, title: str, message: str, data: dict[str, str]) -> str:
        payload = {
            "notification": {
                "title": title,
                "body": message,
            },
            "data": data,
            "priority": "high",
        }
        return json.dumps(payload)


aws_service = AWSService()

import boto3
from botocore.config import Config

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


aws_service = AWSService()

from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = Field(default="Asistencia Vehicular API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_cors_origins: str = Field(default="http://localhost:4200", alias="APP_CORS_ORIGINS")

    database_engine: str = Field(default="postgresql", alias="DATABASE_ENGINE")
    database_host: str = Field(default="localhost", alias="DATABASE_HOST")
    database_name: str = Field(default="asistencia_vehicular", alias="DATABASE_NAME")
    database_user: str = Field(default="postgres", alias="DATABASE_USER")
    database_password: str = Field(default="postgres", alias="DATABASE_PASSWORD")
    database_port: int = Field(default=5432, alias="DATABASE_PORT")

    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: str = Field(default="test", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="test", alias="AWS_SECRET_ACCESS_KEY")
    aws_s3_bucket: str = Field(default="asistencia-vehicular-evidencias", alias="AWS_S3_BUCKET")
    aws_sqs_queue_url: str = Field(
        default="http://localhost:4566/000000000000/asistencia-vehicular-events",
        alias="AWS_SQS_QUEUE_URL",
    )
    aws_sns_topic_arn: str = Field(
        default="arn:aws:sns:us-east-1:000000000000:asistencia-vehicular-notifications",
        alias="AWS_SNS_TOPIC_ARN",
    )
    aws_sns_platform_application_arn: str | None = Field(
        default=None,
        alias="AWS_SNS_PLATFORM_APPLICATION_ARN",
    )
    aws_push_enabled: bool = Field(default=True, alias="AWS_PUSH_ENABLED")
    aws_endpoint_url: str | None = Field(default=None, alias="AWS_ENDPOINT_URL")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.app_cors_origins.split(",") if origin.strip()]

    @cached_property
    def database_url(self) -> str:
        return (
            f"{self.database_engine}+asyncpg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


settings = Settings()

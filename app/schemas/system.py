from pydantic import BaseModel


class SystemInfo(BaseModel):
    service: str
    environment: str
    aws_region: str
    storage_bucket: str

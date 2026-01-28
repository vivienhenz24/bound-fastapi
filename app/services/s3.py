from io import BytesIO

import boto3

from app.core.config import settings


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
    )


def upload_file(key: str, data: bytes, content_type: str = "application/octet-stream"):
    client = get_s3_client()
    client.upload_fileobj(
        BytesIO(data),
        settings.s3_bucket_name,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def download_file(key: str) -> bytes:
    client = get_s3_client()
    buffer = BytesIO()
    client.download_fileobj(settings.s3_bucket_name, key, buffer)
    buffer.seek(0)
    return buffer.read()


def generate_presigned_url(key: str, expiration: int = 3600) -> str:
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": key},
        ExpiresIn=expiration,
    )

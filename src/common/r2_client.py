import boto3
from botocore.config import Config

from src.common.config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET_NAME,
    R2_ENDPOINT,
    R2_SECRET_ACCESS_KEY,
)

s3 = boto3.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        s3={"addressing_style": "virtual"},
        signature_version="s3v4",
        retries={"max_attempts": 3},
    ),
)


def upload_file(file_path: str, key: str):
    s3.upload_file(file_path, R2_BUCKET_NAME, key)


def download_file(key: str, file_path: str):
    s3.download_file(R2_BUCKET_NAME, key, file_path)

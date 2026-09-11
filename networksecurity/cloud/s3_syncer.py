from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import boto3


class S3Sync:
    def __init__(self, client=None):
        self._client = client or boto3.client("s3")

    @staticmethod
    def _parse(uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise ValueError(f"invalid S3 URI: {uri}")
        return parsed.netloc, parsed.path.lstrip("/")

    def upload_file(self, file_path: str, aws_url: str) -> None:
        bucket, key = self._parse(aws_url)
        if not key:
            raise ValueError("S3 object URL must include a key")
        self._client.upload_file(file_path, bucket, key)

    def sync_folder_to_s3(self, folder: str, aws_bucket_url: str) -> None:
        bucket, prefix = self._parse(aws_bucket_url)
        root = Path(folder)
        if not root.exists():
            raise FileNotFoundError(folder)

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            key = f"{prefix.rstrip('/')}/{relative}" if prefix else relative
            self._client.upload_file(str(path), bucket, key)

    def sync_folder_from_s3(self, folder: str, aws_bucket_url: str) -> None:
        bucket, prefix = self._parse(aws_bucket_url)
        destination = Path(folder)
        destination.mkdir(parents=True, exist_ok=True)

        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if key.endswith("/"):
                    continue
                relative = key[len(prefix):].lstrip("/") if prefix else key
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                self._client.download_file(bucket, key, str(target))

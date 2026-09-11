from pathlib import Path

import pytest

from networksecurity.cloud.s3_syncer import S3Sync


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages


class FakeS3Client:
    def __init__(self):
        self.uploads = []
        self.downloads = []
        self.paginator = FakePaginator(
            [
                {
                    "Contents": [
                        {"Key": "prefix/one.txt"},
                        {"Key": "prefix/nested/two.txt"},
                        {"Key": "prefix/folder/"},
                    ]
                }
            ]
        )

    def upload_file(self, file_path, bucket, key):
        self.uploads.append((file_path, bucket, key))

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self.paginator

    def download_file(self, bucket, key, target):
        self.downloads.append((bucket, key, target))
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key, encoding="utf-8")


def test_s3_sync_uploads_files_with_stable_relative_keys(tmp_path):
    client = FakeS3Client()
    sync = S3Sync(client)
    root = tmp_path / "artifacts"
    (root / "nested").mkdir(parents=True)
    (root / "one.txt").write_text("one", encoding="utf-8")
    (root / "nested" / "two.txt").write_text("two", encoding="utf-8")

    sync.upload_file(str(root / "one.txt"), "s3://bucket/releases/current.json")
    sync.sync_folder_to_s3(str(root), "s3://bucket/prefix")

    assert (str(root / "one.txt"), "bucket", "releases/current.json") in client.uploads
    assert (str(root / "one.txt"), "bucket", "prefix/one.txt") in client.uploads
    assert (str(root / "nested" / "two.txt"), "bucket", "prefix/nested/two.txt") in client.uploads


def test_s3_sync_downloads_prefix_and_rejects_invalid_urls(tmp_path):
    client = FakeS3Client()
    sync = S3Sync(client)
    destination = tmp_path / "download"

    sync.sync_folder_from_s3(str(destination), "s3://bucket/prefix")

    assert (destination / "one.txt").read_text(encoding="utf-8") == "prefix/one.txt"
    assert (destination / "nested" / "two.txt").exists()
    assert client.paginator.calls == [{"Bucket": "bucket", "Prefix": "prefix"}]

    with pytest.raises(ValueError, match="invalid S3 URI"):
        S3Sync._parse("https://example.com/not-s3")
    with pytest.raises(ValueError, match="include a key"):
        sync.upload_file("unused", "s3://bucket")
    with pytest.raises(FileNotFoundError):
        sync.sync_folder_to_s3(str(tmp_path / "missing"), "s3://bucket/prefix")

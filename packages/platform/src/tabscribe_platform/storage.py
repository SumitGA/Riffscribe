"""Object storage through the S3 API: Cloudflare R2 in production, SeaweedFS locally (ADR-0002).

Only plain S3 calls, so any S3-compatible store works. Clients never get credentials, only
presigned URLs that expire within `Settings.presign_ttl_s` (15 minutes at most).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from tabscribe_platform.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

# User IDs are JWT `sub` claims. Restricting them keeps every key under its own user's prefix.
_USER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def user_prefix(user_id: str) -> str:
    """`users/{user_id}/`: the prefix every object of this user lives under (tenant isolation)."""
    if not _USER_ID.fullmatch(user_id):
        raise ValueError(f"invalid user id: {user_id!r}")
    return f"users/{user_id}/"


def job_prefix(user_id: str, job_id: str) -> str:
    """`users/{user_id}/jobs/{job_id}/`: a job's stages keep their artifacts below this."""
    return f"{user_prefix(user_id)}jobs/{_segment(job_id)}/"


def job_key(user_id: str, job_id: str, stage: str, name: str) -> str:
    """`users/{user_id}/jobs/{job_id}/{stage}/{name}`, the layout in CLAUDE.md's job flow."""
    return f"{job_prefix(user_id, job_id)}{_segment(stage)}/{_segment(name)}"


def _segment(value: str) -> str:
    if not _SEGMENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid key segment: {value!r}")
    return value


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None
    etag: str


@dataclass(frozen=True)
class PresignedRequest:
    """What a client needs to make the request: it must send `headers` exactly as given."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_in_s: int = 0


def _client(settings: Settings, endpoint_url: str | None) -> "S3Client":
    config = Config(
        signature_version="s3v4",
        # Path-style URLs (endpoint/bucket/key) work on R2, SeaweedFS and S3 alike.
        s3={"addressing_style": "path"},
        retries={"mode": "standard"},
        # Recent botocore adds CRC checksums to every upload; R2 and SeaweedFS don't accept all
        # of them, and a presigned PUT would require the client to send one. Only when required.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3", endpoint_url=endpoint_url, region_name=settings.s3_region, config=config
    )


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.presign_ttl_s = settings.presign_ttl_s
        self._s3 = _client(settings, settings.s3_endpoint_url)
        # Presigning is local (no request is sent), so a second client for the public endpoint
        # costs nothing. The signature covers the host, so it must be the one clients use.
        self._presigner = (
            _client(settings, settings.s3_public_endpoint_url)
            if settings.s3_public_endpoint_url
            else self._s3
        )

    def presign_put(self, key: str, content_type: str) -> PresignedRequest:
        """URL for a client to upload one object. The size is checked afterwards with `head`."""
        url = self._presigner.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self.presign_ttl_s,
        )
        return PresignedRequest("PUT", url, {"Content-Type": content_type}, self.presign_ttl_s)

    def presign_get(self, key: str, download_name: str | None = None) -> PresignedRequest:
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        url = self._presigner.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=self.presign_ttl_s
        )
        return PresignedRequest("GET", url, {}, self.presign_ttl_s)

    def head(self, key: str) -> ObjectInfo | None:
        """Size and type of an object, or None if it doesn't exist."""
        try:
            response = self._s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return ObjectInfo(
            size=response["ContentLength"],
            content_type=response.get("ContentType"),
            etag=response["ETag"].strip('"'),
        )

    def upload_file(self, path: Path, key: str, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self._s3.upload_file(str(path), self.bucket, key, ExtraArgs=extra)

    def download_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self.bucket, key, str(path))

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix`; returns how many there were."""
        if not prefix.endswith("/"):
            raise ValueError("prefix must end with '/' so it can't match a sibling's keys")
        keys = self.list_keys(prefix)
        for start in range(0, len(keys), 1000):  # DeleteObjects takes at most 1000 keys
            batch = keys[start : start + 1000]
            self._s3.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
        return len(keys)

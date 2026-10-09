"""Postgres backups in R2 for staging (ADR-0010). Runs inside the API image, which has boto3 and
the S3 settings:

    pg_dump ... | python backup_to_r2.py upload      # stdin -> backups/<UTC time>.dump
    python backup_to_r2.py prune                      # delete backups older than KEEP_DAYS
    python backup_to_r2.py list                       # newest last
    python backup_to_r2.py download <key> > file      # for a restore (docs/staging.md)
"""

import os
import sys
from datetime import UTC, datetime, timedelta

import boto3

PREFIX = "backups/"
KEEP_DAYS = 14


def client():  # type: ignore[no-untyped-def]
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        region_name=os.environ.get("S3_REGION", "auto"),
    )


def main() -> None:
    s3, bucket = client(), os.environ["S3_BUCKET"]
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "upload":
        key = f"{PREFIX}{datetime.now(UTC):%Y-%m-%dT%H%M%SZ}.dump"
        s3.upload_fileobj(sys.stdin.buffer, bucket, key)
        size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
        if size == 0:
            s3.delete_object(Bucket=bucket, Key=key)
            sys.exit("backup failed: the dump was empty")
        print(f"uploaded {key} ({size} bytes)")
    elif command in ("prune", "list"):
        cutoff = datetime.now(UTC) - timedelta(days=KEEP_DAYS)
        pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX)
        objects = sorted(
            (o for page in pages for o in page.get("Contents", [])), key=lambda o: o["Key"]
        )
        for o in objects:
            if command == "list":
                print(o["Key"], o["Size"])
            elif o["LastModified"] < cutoff and o is not objects[-1]:  # always keep the newest
                s3.delete_object(Bucket=bucket, Key=o["Key"])
                print(f"deleted {o['Key']}")
    elif command == "download" and len(sys.argv) == 3:
        s3.download_fileobj(bucket, sys.argv[2], sys.stdout.buffer)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

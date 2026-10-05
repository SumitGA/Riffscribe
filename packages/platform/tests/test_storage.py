import urllib.request
from pathlib import Path
from urllib.error import HTTPError

import pytest

from tabscribe_platform.storage import ObjectStore, job_key, job_prefix, user_prefix


@pytest.mark.unit
def test_keys_follow_the_job_layout() -> None:
    assert user_prefix("alice") == "users/alice/"
    assert job_prefix("alice", "j1") == "users/alice/jobs/j1/"
    assert job_key("alice", "j1", "tab", "tab.musicxml") == "users/alice/jobs/j1/tab/tab.musicxml"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("user_id", "job_id", "stage", "name"),
    [
        ("", "j1", "tab", "x"),
        ("alice/../bob", "j1", "tab", "x"),
        ("alice", "..", "tab", "x"),
        ("alice", "j1", "tab/../..", "x"),
        ("alice", "j1", "tab", "a/b"),
        ("alice", "j1", "tab", "."),
    ],
)
def test_keys_cannot_escape_the_user_prefix(
    user_id: str, job_id: str, stage: str, name: str
) -> None:
    with pytest.raises(ValueError, match="invalid"):
        job_key(user_id, job_id, stage, name)


def _request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body: bytes = response.read()
        return body


@pytest.mark.integration
def test_presigned_upload_and_download(object_store: ObjectStore, s3_user: str) -> None:
    key = job_key(s3_user, "j1", "source", "upload.m4a")
    put = object_store.presign_put(key, "audio/mp4")
    assert put.expires_in_s <= 15 * 60
    _request(put.method, put.url, put.headers, b"fake audio")

    info = object_store.head(key)
    assert info is not None
    assert (info.size, info.content_type) == (10, "audio/mp4")

    get = object_store.presign_get(key, download_name="song.m4a")
    assert _request(get.method, get.url, get.headers) == b"fake audio"


@pytest.mark.integration
def test_presigned_put_rejects_another_content_type(
    object_store: ObjectStore, s3_user: str
) -> None:
    put = object_store.presign_put(job_key(s3_user, "j1", "source", "upload.m4a"), "audio/mp4")
    with pytest.raises(HTTPError) as exc_info:
        _request("PUT", put.url, {"Content-Type": "text/html"}, b"<script>")
    assert exc_info.value.code == 403


@pytest.mark.integration
def test_head_of_missing_object_is_none(object_store: ObjectStore, s3_user: str) -> None:
    assert object_store.head(job_key(s3_user, "j1", "source", "missing")) is None


@pytest.mark.integration
def test_file_round_trip_list_and_delete(
    object_store: ObjectStore, s3_user: str, tmp_path: Path
) -> None:
    source = tmp_path / "in.mid"
    source.write_bytes(b"MThd")
    keys = [job_key(s3_user, job, "transcribe", "notes.mid") for job in ("j1", "j2")]
    for key in keys:
        object_store.upload_file(source, key, "audio/midi")

    assert object_store.list_keys(job_prefix(s3_user, "j1")) == [keys[0]]
    object_store.download_file(keys[0], tmp_path / "out" / "notes.mid")
    assert (tmp_path / "out" / "notes.mid").read_bytes() == b"MThd"

    assert object_store.delete_prefix(user_prefix(s3_user)) == 2
    assert object_store.list_keys(user_prefix(s3_user)) == []


@pytest.mark.integration
def test_delete_prefix_needs_a_trailing_slash(object_store: ObjectStore) -> None:
    with pytest.raises(ValueError, match="end with '/'"):
        object_store.delete_prefix("users/alice")

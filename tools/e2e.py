"""End-to-end check of the running backend, the way the mobile app uses it (`make e2e`).

Talks HTTP to the API (API_URL, default http://localhost:8000) and uploads straight to object
storage with the presigned URLs, like a phone would. Needs JWT_ISSUER and JWT_DEV_SECRET to
mint dev tokens (the Makefile passes them), or, against staging, which only accepts real
Clerk tokens, E2E_TOKEN and E2E_OTHER_TOKEN for two different users (`make e2e-staging`,
docs/staging.md). Exits non-zero on the first failed check.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from api.auth import AuthSettings, issue_dev_token

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
FIXTURES = Path(__file__).parent / "e2e_fixtures"
TIMEOUT_S = float(os.environ.get("E2E_TIMEOUT_S", "180"))


class CheckFailedError(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailedError(message)


def request(
    method: str,
    url: str,
    token: str | None = None,
    body: Any = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    all_headers = dict(headers or {})
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def api(method: str, path: str, token: str | None = None, body: Any = None) -> tuple[int, Any]:
    status, raw = request(method, API + path, token, body)
    return status, json.loads(raw) if raw else None


def transcribe(token: str, clip: Path, content_type: str, instrument: str) -> dict[str, Any]:
    """Create, upload, submit and wait; returns the finished job."""
    data = clip.read_bytes()
    status, created = api(
        "POST",
        "/jobs",
        token,
        {"instrument": instrument, "content_type": content_type, "size_bytes": len(data)},
    )
    check(status == 201, f"create job: {status} {created}")
    upload = created["upload"]
    status, _ = request(upload["method"], upload["url"], data=data, headers=upload["headers"])
    check(status == 200, f"presigned upload: {status}")
    job_id = created["job"]["id"]
    status, job = api("POST", f"/jobs/{job_id}/submit", token)
    check(status == 200 and job["status"] == "queued", f"submit: {status} {job}")

    deadline = time.monotonic() + TIMEOUT_S
    while job["status"] not in ("succeeded", "failed"):
        check(time.monotonic() < deadline, f"job {job_id} still {job['status']} after {TIMEOUT_S}s")
        time.sleep(0.5)
        _, job = api("GET", f"/jobs/{job_id}", token)
    return dict(job)


def step(name: str) -> None:
    print(f"  ok  {name}", flush=True)


def main() -> int:
    alice, mallory = os.environ.get("E2E_TOKEN"), os.environ.get("E2E_OTHER_TOKEN")
    if not (alice and mallory):
        auth = AuthSettings()
        alice = issue_dev_token(auth, f"e2e-{uuid.uuid4().hex[:8]}")
        mallory = issue_dev_token(auth, f"e2e-{uuid.uuid4().hex[:8]}")
    print(f"e2e against {API}")
    try:
        status, _ = api("GET", "/readyz")
        check(status == 200, f"/readyz: {status}")
        step("API ready (Postgres, Redis)")
        check(api("GET", "/me")[0] == 401, "/me without a token should be 401")
        step("requests without a token are refused")
        status, me = api("GET", "/me", alice)
        check(status == 200, f"/me: {status}")
        used_before = me["jobs_this_month"]  # nonzero for a reused staging user

        start = time.monotonic()
        job = transcribe(alice, FIXTURES / "piano.m4a", "audio/mp4", "guitar")
        check(job["status"] == "succeeded", f"m4a job: {job['status']} {job['error']}")
        stages = {s["stage"]: s["status"] for s in job["stages"]}
        check(set(stages.values()) == {"succeeded"}, f"stages: {stages}")
        step(f"m4a (AAC) guitar job: 6 stages in {time.monotonic() - start:.1f}s")

        outputs = job["outputs"]
        for name in ("musicxml", "tab_musicxml", "midi"):
            out = outputs[name]
            status, body = request(out["method"], out["url"], headers=out["headers"])
            check(status == 200 and len(body) > 0, f"download {name}: {status}")
            if name != "midi":
                check(b"<score-partwise" in body, f"{name} is not MusicXML")
            else:
                check(body.startswith(b"MThd"), "midi is not a MIDI file")
        step("MusicXML, tab MusicXML and MIDI download through presigned URLs")

        again = transcribe(alice, FIXTURES / "piano.m4a", "audio/mp4", "guitar")
        cached = [s["stage"] for s in again["stages"] if s["status"] == "cached"]
        check(again["status"] == "succeeded" and len(cached) == 5, f"dedup: {again['stages']}")
        step("the same upload again reuses the results (5 stages cached)")

        piano = transcribe(alice, FIXTURES / "piano.mp3", "audio/mpeg", "piano")
        stages = {s["stage"]: s["status"] for s in piano["stages"]}
        check(piano["status"] == "succeeded" and stages["tab"] == "skipped", f"mp3: {stages}")
        check(piano["outputs"]["tab_musicxml"] is None, "piano jobs have no tab")
        step("mp3 piano job: tab skipped")

        bad = transcribe(alice, Path(__file__), "audio/mp4", "guitar")  # not audio
        check(bad["status"] == "failed", f"bad input: {bad['status']}")
        check(bad["error"]["code"] == "invalid_input", f"bad input error: {bad['error']}")
        check("/" not in (bad["error"]["message"] or ""), "error message leaks a path")
        step(f"non-audio upload fails cleanly: {bad['error']['message']!r}")

        check(api("GET", f"/jobs/{job['id']}", mallory)[0] == 404, "other users must get 404")
        step("another user's job is a 404")

        status, me = api("GET", "/me", alice)
        check(status == 200 and me["jobs_this_month"] - used_before == 4, f"/me: {me}")
        step("quota counted 4 submitted jobs")
    except CheckFailedError as exc:
        print(f"  FAIL {exc}", file=sys.stderr)
        return 1
    print("e2e passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

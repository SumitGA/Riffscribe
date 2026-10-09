"""Tells the user a job finished: a push notification on each device they registered (the app
registers Expo push tokens through the API), or only a log line (`WORKER_NOTIFIER=log`, the
default, for local runs and tests)."""

import json
import logging
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from tabscribe_platform.db import Job, JobStatus, PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
# Expo accepts up to 100 messages per request; a user has a handful of devices at most.
MAX_DEVICES = 100

# Sends messages to Expo's push service and returns its parsed JSON answer.
Sender = Callable[[list[dict[str, Any]]], dict[str, Any]]


class Notifier(Protocol):
    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None: ...


class LogNotifier:
    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None:
        logger.info("notify user: job %s %s", job_id, status, extra={"user_id": user_id})


def expo_sender(access_token: str | None = None, timeout_s: float = 10) -> Sender:
    """POSTs to Expo's push API. The access token is only needed if push security is turned on
    for the Expo project."""

    def send(messages: list[dict[str, Any]]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = urllib.request.Request(
            EXPO_PUSH_URL, data=json.dumps(messages).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            result: dict[str, Any] = json.load(response)
            return result

    return send


def message_for(job: Job, status: JobStatus) -> tuple[str, str]:
    """The notification's title and body."""
    instrument = "Guitar" if job.config.get("instrument") == "guitar" else "Piano"
    name = job.name or f"{instrument} take"
    if status is JobStatus.SUCCEEDED:
        return "Your score is ready", f"“{name}” is transcribed. Tap to see and hear it."
    return f"Couldn't transcribe “{name}”", job.error_message or "Something went wrong."


class ExpoPushNotifier:
    """Expo push notifications (docs.expo.dev/push-notifications/sending-notifications).

    Failures are logged, never raised: a notification that can't be sent must not affect the
    job, which has already finished. Devices Expo reports as no longer registered (app
    uninstalled, notifications revoked) are forgotten.
    """

    def __init__(self, sessions: sessionmaker[Session], send: Sender) -> None:
        self._sessions = sessions
        self._send = send

    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None:
        try:
            self._notify(user_id, job_id, status)
        except Exception:
            logger.exception("could not send push notifications", extra={"user_id": user_id})

    def _notify(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None:
        with self._sessions() as session:
            job = session.scalars(
                select(Job).where(Job.id == job_id, Job.user_id == user_id)
            ).first()
            tokens = session.scalars(
                select(PushToken.token).where(PushToken.user_id == user_id).limit(MAX_DEVICES)
            ).all()
            if job is None or not tokens:
                return
            title, body = message_for(job, status)

        messages = [
            {
                "to": token,
                "title": title,
                "body": body,
                "data": {"jobId": str(job_id)},
                "sound": "default",
                "channelId": "default",
            }
            for token in tokens
        ]
        tickets = self._send(messages).get("data", [])
        gone = [
            token
            for token, ticket in zip(tokens, tickets, strict=False)
            if ticket.get("status") == "error"
            and ticket.get("details", {}).get("error") == "DeviceNotRegistered"
        ]
        if gone:
            with self._sessions() as session:
                session.execute(delete(PushToken).where(PushToken.token.in_(gone)))
                session.commit()
        logger.info(
            "push notification sent to %d device(s), %d gone",
            len(tokens) - len(gone),
            len(gone),
            extra={"user_id": user_id},
        )

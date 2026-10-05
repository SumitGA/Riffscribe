"""Tells the user a job finished. Expo push notifications come in Phase 3 (device tokens are
registered by the app); until then this only logs."""

import logging
import uuid
from typing import Protocol

from tabscribe_platform.db import JobStatus

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None: ...


class LogNotifier:
    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None:
        logger.info("notify user: job %s %s", job_id, status, extra={"user_id": user_id})

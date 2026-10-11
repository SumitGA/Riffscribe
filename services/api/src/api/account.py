"""Your account: accepting the terms of use, and deleting the account (Google Play and the App
Store require deletion in the app).

`DELETE /me` removes everything the user has here (their transcriptions, score versions, push
tokens and every stored file) and then their Clerk sign-in. It is safe to repeat: if Clerk
can't be reached, the app calls it again and only the Clerk step is left to do.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.auth import CurrentUserDep
from api.deps import ApiSettingsDep, SessionDep, StoreDep
from api.schemas import AcceptTermsRequest
from tabscribe_platform.db import User
from tabscribe_platform.storage import user_prefix

router = APIRouter(prefix="/me", tags=["me"])
logger = logging.getLogger(__name__)

# The terms of use and privacy policy in force (infra/site/terms.html carries the same date).
# Changing them means a new version here: every user accepts again before their next upload.
TERMS_VERSION = "2026-10-11"
TERMS_REQUIRED = "accept the terms of use before uploading"

CLERK_API = "https://api.clerk.com/v1"
# Cloudflare in front of Clerk refuses Python's default "Python-urllib" agent (error 1010).
USER_AGENT = "riffscribe-api/1.0"


def terms_accepted(session: Session, user_id: str) -> bool:
    accepted = session.scalar(select(User.terms_version).where(User.id == user_id))
    return accepted == TERMS_VERSION


@router.put("/terms", status_code=status.HTTP_204_NO_CONTENT)
def accept_terms(body: AcceptTermsRequest, user: CurrentUserDep, session: SessionDep) -> None:
    """The user confirms the terms (they have the right to use what they upload, ADR-0009)."""
    if body.version != TERMS_VERSION:  # an app showing old terms must show the new ones first
        raise HTTPException(status.HTTP_409_CONFLICT, f"the current terms are {TERMS_VERSION}")
    now = datetime.now(UTC)
    session.execute(
        insert(User)
        .values(id=user.id, terms_version=TERMS_VERSION, terms_accepted_at=now)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={"terms_version": TERMS_VERSION, "terms_accepted_at": now},
        )
    )
    session.commit()
    logger.info("terms accepted", extra={"terms_version": TERMS_VERSION})


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user: CurrentUserDep, session: SessionDep, store: StoreDep, settings: ApiSettingsDep
) -> None:
    # The database first (jobs, versions and push tokens cascade from the user), then files: a
    # failure afterwards can leave unreachable files, never a user without theirs.
    session.execute(delete(User).where(User.id == user.id))
    session.commit()
    try:
        removed = store.delete_prefix(user_prefix(user.id))
    except Exception:
        logger.exception("could not delete the account's files")
        removed = -1
    logger.info("account data deleted", extra={"objects": removed})

    if settings.clerk_secret_key is None:  # local runs and tests: no Clerk account to delete
        return
    try:
        delete_clerk_user(user.id, settings.clerk_secret_key.get_secret_value())
    except Exception as exc:
        logger.exception("could not delete the Clerk user")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "your data is deleted, but signing you out of Riffscribe for good failed; try again",
        ) from exc
    logger.info("account deleted")


def delete_clerk_user(user_id: str, secret_key: str) -> None:
    """Clerk's Backend API: DELETE /users/{id}. A user that is already gone counts as done."""
    request = urllib.request.Request(
        f"{CLERK_API}/users/{user_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {secret_key}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        if error.code != status.HTTP_404_NOT_FOUND:
            raise

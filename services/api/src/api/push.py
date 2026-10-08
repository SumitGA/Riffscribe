"""Devices that get "your score is ready" notifications (Expo push tokens).

The app registers its token after the user allows notifications, and removes it on sign-out.
The worker sends through Expo's push service (worker.notify).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from api.auth import CurrentUserDep
from api.deps import SessionDep
from tabscribe_platform.db import PUSH_TOKEN_MAX, PushToken, User

router = APIRouter(prefix="/me/push-tokens", tags=["push"])

# Expo's token format; anything else would only fail later, at send time.
TOKEN_PATTERN = r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$"


Token = Annotated[str, Path(max_length=PUSH_TOKEN_MAX)]


class PushTokenIn(BaseModel):
    token: str = Field(max_length=PUSH_TOKEN_MAX, pattern=TOKEN_PATTERN)
    platform: Literal["ios", "android"]


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
def register_push_token(body: PushTokenIn, user: CurrentUserDep, session: SessionDep) -> None:
    """Notify this device about the caller's jobs. Safe to repeat; a device that was another
    user's moves to the caller (it signed in as someone else)."""
    session.execute(insert(User).values(id=user.id).on_conflict_do_nothing())
    session.execute(
        insert(PushToken)
        .values(token=body.token, user_id=user.id, platform=body.platform)
        .on_conflict_do_update(
            index_elements=[PushToken.token],
            set_={"user_id": user.id, "platform": body.platform},
        )
    )
    session.commit()


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
def remove_push_token(token: Token, user: CurrentUserDep, session: SessionDep) -> None:
    """Stop notifying this device (sign-out, or notifications turned off). Only the caller's own
    tokens can be removed; anything else is quietly ignored, so this can't probe tokens."""
    session.execute(delete(PushToken).where(PushToken.token == token, PushToken.user_id == user.id))
    session.commit()

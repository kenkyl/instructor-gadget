"""Sessions in Redis + the get_current_user dependency.

Phase 1 login is "pick a seeded user". Everything else in the app only depends on
`CurrentUserDep`, so swapping in Google OAuth later is a change to this file, not the app.

Session storage: `sess:{token}` is a Redis **hash** (flat, tiny, read on every request) with a
TTL; the browser only holds the opaque token in an HttpOnly cookie (ADR-0011).
"""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis

from app.config import get_settings
from app.deps import RedisDep

SESSION_COOKIE = "sid"


class CurrentUser(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


def session_key(token: str) -> str:
    return f"sess:{token}"


async def create_session(redis: Redis, user: CurrentUser) -> str:
    token = secrets.token_urlsafe(32)
    key = session_key(token)
    # MULTI/EXEC so the hash never exists without its TTL.
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(
            key,
            mapping={
                "user_id": str(user.id),
                "username": user.username,
                "display_name": user.display_name,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        pipe.expire(key, get_settings().session_ttl_seconds)
        await pipe.execute()
    return token


async def delete_session(redis: Redis, token: str) -> None:
    await redis.delete(session_key(token))


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,  # JS can't read it, so XSS can't steal the session
        samesite="lax",  # not sent on cross-site POSTs (basic CSRF protection)
        secure=settings.cookie_secure,
        path="/",
    )


async def get_current_user(
    redis: RedisDep, sid: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None
) -> CurrentUser:
    if sid:
        data = await redis.hgetall(session_key(sid))
        if data:
            return CurrentUser(
                id=uuid.UUID(data["user_id"]),
                username=data["username"],
                display_name=data["display_name"],
            )
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]

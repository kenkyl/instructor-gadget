"""Login (pick a seeded user), logout, and who-am-I."""

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import (
    SESSION_COOKIE,
    CurrentUser,
    CurrentUserDep,
    create_session,
    delete_session,
    set_session_cookie,
)
from app.deps import Db, RedisDep
from app.models import User
from app.services.dashboard import get_dashboard

router = APIRouter(tags=["auth"])


class SeededUser(BaseModel):
    username: str
    display_name: str


class LoginRequest(BaseModel):
    username: str


@router.get("/users/seeded")
async def list_seeded_users(db: Db) -> list[SeededUser]:
    """Phase 1 login picker. Replaced by Google sign-in in P2."""
    users = await db.scalars(select(User).order_by(User.username))
    return [SeededUser(username=u.username, display_name=u.display_name) for u in users]


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response, db: Db, redis: RedisDep) -> CurrentUser:
    user = await db.scalar(select(User).where(User.username == body.username))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown user")
    current = CurrentUser(id=user.id, username=user.username, display_name=user.display_name)
    token = await create_session(redis, current)
    set_session_cookie(response, token)
    await get_dashboard(db, redis, current)  # warm the cache so the first page load is fast
    return current


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    redis: RedisDep,
    sid: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if sid:
        await delete_session(redis, sid)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: CurrentUserDep) -> CurrentUser:
    return user

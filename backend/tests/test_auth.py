import redis

from app.auth import SESSION_COOKIE, session_key
from app.config import get_settings


def test_seeded_users_listed(client) -> None:
    usernames = [u["username"] for u in client.get("/api/users/seeded").json()]
    assert usernames == ["dana", "kyle", "priya"]


def test_me_requires_login(client) -> None:
    assert client.get("/api/me").status_code == 401


def test_unknown_user_cannot_log_in(client) -> None:
    assert client.post("/api/auth/login", json={"username": "mallory"}).status_code == 404


def test_login_session_logout(client) -> None:
    resp = client.post("/api/auth/login", json={"username": "dana"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "dana"

    cookie = resp.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie

    # The session is a Redis hash with a TTL.
    token = client.cookies[SESSION_COOKIE]
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    assert r.type(session_key(token)) == "hash"
    assert r.hget(session_key(token), "username") == "dana"
    assert 0 < r.ttl(session_key(token)) <= 8 * 60 * 60

    assert client.get("/api/me").json()["username"] == "dana"

    assert client.post("/api/auth/logout").status_code == 204
    assert not r.exists(session_key(token))
    assert client.get("/api/me").status_code == 401

import hashlib
import json
import os
import secrets
import time
import unicodedata
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import User, db

redis = Redis.from_url(
    os.environ.get("REDIS_URL", "redis://127.0.0.1:56379/0"),
    decode_responses=True,
    socket_timeout=2,
)
passwords = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
COOKIE = "__Host-mi_session" if os.environ.get("COOKIE_SECURE") == "1" else "mi_session"
ORIGIN = os.environ.get("WEB_ORIGIN", "http://localhost:33017")
IDLE = 1800
ABSOLUTE = 86400


def fail(status, code):
    raise HTTPException(status, code)


def identity(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        fail(422, "invalid_id")
    result = int(value)
    if not 1 <= result <= 9223372036854775807:
        fail(422, "invalid_id")
    return result


def normalize(account: str) -> str:
    result = unicodedata.normalize("NFKC", account).casefold().strip()
    if not 4 <= len(result) <= 256:
        fail(422, "invalid_account")
    return result


def check_origin(request: Request):
    if request.headers.get("origin") != ORIGIN:
        fail(403, "origin_denied")


def check_password(encoded, plain):
    try:
        return passwords.verify(encoded, plain)
    except VerificationError:
        return False


def public_user(user):
    return {
        "id": str(user.id),
        "name": "已刪除使用者" if user.deleted_at else user.name,
        "avatar_url": user.profile.get("avatar_url", ""),
        "bio": user.profile.get("bio", ""),
    }


def device(request):
    ua = request.headers.get("user-agent", "").lower()
    return "mobile" if any(value in ua for value in ("android", "iphone", "ipad")) else "browser"


async def create_session(user, request, response):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    payload = json.dumps({"user_id": user.id, "csrf": csrf, "expires": time.time() + ABSOLUTE})
    registry = f"auth:device:{user.id}:{device(request)}"
    script = """
    local old=redis.call('GET',KEYS[1])
    if old then redis.call('DEL','auth:session:'..old) end
    redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[4])
    redis.call('SET',KEYS[2],ARGV[2],'EX',ARGV[3])
    redis.call('SADD',KEYS[3],ARGV[1])
    redis.call('EXPIRE',KEYS[3],ARGV[4])
    return 1
    """
    try:
        await redis.eval(
            script,
            3,
            registry,
            f"auth:session:{token}",
            f"auth:user:{user.id}",
            token,
            payload,
            IDLE,
            ABSOLUTE,
        )
    except RedisError:
        fail(503, "session_unavailable")
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=COOKIE.startswith("__Host-"),
        samesite="lax",
        path="/",
        max_age=ABSOLUTE,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {**public_user(user), "role": user.role, "csrf_token": csrf}


async def revoke_user(user_id):
    try:
        tokens = await redis.smembers(f"auth:user:{user_id}")
        keys = [f"auth:session:{token}" for token in tokens]
        keys += [
            f"auth:user:{user_id}",
            f"auth:device:{user_id}:browser",
            f"auth:device:{user_id}:mobile",
        ]
        await redis.delete(*keys)
    except RedisError:
        # Every authentication also checks the canonical SQL tombstone/role.
        pass


async def current_user(request: Request, session: AsyncSession = Depends(db)):
    token = request.cookies.get(COOKIE)
    if not token:
        fail(401, "authentication_required")
    try:
        raw = await redis.get(f"auth:session:{token}")
        if not raw:
            fail(401, "session_expired")
        data = json.loads(raw)
        remaining = int(data["expires"] - time.time())
        if remaining <= 0:
            await redis.delete(f"auth:session:{token}")
            fail(401, "session_expired")
        user = await session.get(User, data["user_id"])
        if not user or user.deleted_at or user.role == "ban":
            fail(401, "session_revoked")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), data["csrf"]):
                fail(403, "csrf_denied")
        await redis.expire(f"auth:session:{token}", min(IDLE, remaining))
        request.state.auth = data
        return user
    except RedisError:
        fail(503, "session_unavailable")


async def admin(user: User = Depends(current_user)):
    if user.role != "admin":
        fail(403, "administrator_required")
    return user


def owner(row, user):
    if row.creator_id != user.id and user.role != "admin":
        fail(403, "owner_required")


async def active(session, model, value, lock=False):
    stmt = select(model).where(model.id == identity(value))
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if not row:
        fail(404, "not_found")
    return row


def now():
    return datetime.now(timezone.utc)


class Bloom:
    """Bounded prefilter; an exact set always determines membership."""

    def __init__(self, values):
        self.exact = frozenset(values)
        self.bits = bytearray(8192)
        for value in self.exact:
            for offset in self.offsets(value):
                self.bits[offset // 8] |= 1 << (offset % 8)

    @staticmethod
    def offsets(value):
        digest = hashlib.sha256(value.encode()).digest()
        return [int.from_bytes(digest[i : i + 4], "big") % 65536 for i in (0, 4, 8)]

    def contains(self, value):
        probable = all(self.bits[o // 8] & (1 << (o % 8)) for o in self.offsets(value))
        return probable and value in self.exact

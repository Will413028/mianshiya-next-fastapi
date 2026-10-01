"""Disposable auth-topology fixture. No passwords, production users, or product APIs."""
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

if os.environ.get("MIANSHIYA_SPIKE") != "1":
    raise RuntimeError("This fixture requires MIANSHIYA_SPIKE=1")

COOKIE = "mianshiya_spike_session"
engine = create_async_engine(os.environ["S0_DATABASE_URL"], pool_size=2, max_overflow=0)
redis = Redis.from_url(os.environ["S0_REDIS_URL"], decode_responses=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE actors (id BIGINT PRIMARY KEY, name TEXT NOT NULL UNIQUE)"))
        await connection.execute(text("INSERT INTO actors VALUES (9007199254740993, 'alice'), (9007199254740995, 'bob')"))
    await redis.ping()
    yield
    await redis.aclose()
    await engine.dispose()


app = FastAPI(lifespan=lifespan)


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str


class Actor(BaseModel):
    id: str
    name: str


async def current_actor(request: Request) -> Actor:
    session = request.cookies.get(COOKIE)
    actor_name = await redis.get(f"s0:session:{session}") if session else None
    if not actor_name:
        raise HTTPException(401, "anonymous")
    async with engine.connect() as connection:
        row = (await connection.execute(text("SELECT id, name FROM actors WHERE name=:name"), {"name": actor_name})).one_or_none()
    if not row:
        raise HTTPException(401, "anonymous")
    return Actor(id=str(row.id), name=row.name)


def same_origin(request: Request) -> None:
    if request.headers.get("origin") != os.environ["S0_WEB_ORIGIN"]:
        raise HTTPException(403, "origin denied")


@app.get("/api/spike/health")
async def health():
    return {"ok": True}


@app.post("/api/spike/login", response_model=Actor)
async def login(body: Login, request: Request, response: Response):
    same_origin(request)
    if body.actor not in {"alice", "bob"}:
        raise HTTPException(422, "unknown synthetic actor")
    session = secrets.token_urlsafe(32)
    await redis.set(f"s0:session:{session}", body.actor, ex=1800)
    response.set_cookie(COOKIE, session, httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "private, no-store"
    return await current_actor_with_name(body.actor)


async def current_actor_with_name(name: str) -> Actor:
    async with engine.connect() as connection:
        row = (await connection.execute(text("SELECT id, name FROM actors WHERE name=:name"), {"name": name})).one()
    return Actor(id=str(row.id), name=row.name)


@app.get("/api/spike/session", response_model=Actor)
async def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    return await current_actor(request)


@app.post("/api/spike/mutation")
async def mutation(request: Request):
    same_origin(request)
    actor = await current_actor(request)
    return {"accepted": actor.name}


@app.post("/api/spike/logout")
async def logout(request: Request, response: Response):
    same_origin(request)
    await current_actor(request)
    session = request.cookies.get(COOKIE)
    await redis.delete(f"s0:session:{session}")
    response.delete_cookie(COOKIE, path="/")
    response.headers["Cache-Control"] = "private, no-store"
    return {"ok": True}

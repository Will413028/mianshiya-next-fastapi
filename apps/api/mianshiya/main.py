import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeout

from . import ai, auth, content, policies, search
from .db import engine
from .security import fail, redis


async def strict_query(request: Request):
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant:
        pending, known = [dependant], set()
        while pending:
            dependency = pending.pop()
            known.update(param.alias for param in dependency.query_params)
            pending.extend(dependency.dependencies)
        if set(request.query_params.keys()) - known:
            fail(422, "unknown_query_fields")


@asynccontextmanager
async def lifespan(app):
    yield
    await search.es.close()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(
    title="面試練習 API",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(strict_query), Depends(policies.guard_request)],
)
for router in (auth.router, search.router, content.router, ai.router, policies.router):
    app.include_router(router)


@app.get("/api/v1/health", operation_id="health")
async def health():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    await redis.ping()
    return {"ok": True}


@app.exception_handler(HTTPException)
async def problem(request, error):
    return JSONResponse(
        {
            "type": "about:blank",
            "title": str(error.detail),
            "status": error.status_code,
            "code": str(error.detail),
            "detail": str(error.detail),
            "request_id": uuid.uuid4().hex,
        },
        status_code=error.status_code,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_problem(request, error):
    return JSONResponse(
        {
            "type": "about:blank",
            "title": "validation_failed",
            "status": 422,
            "code": "validation_failed",
            "detail": "輸入資料不符合契約",
            "request_id": uuid.uuid4().hex,
            "errors": [{"field": list(e["loc"]), "type": e["type"]} for e in error.errors()],
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict_problem(request, error):
    return JSONResponse(
        {
            "type": "about:blank",
            "title": "constraint_conflict",
            "status": 409,
            "code": "constraint_conflict",
            "detail": "資料衝突",
            "request_id": uuid.uuid4().hex,
        },
        status_code=409,
    )


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
@app.exception_handler(RedisError)
async def dependency_problem(request, error):
    return JSONResponse(
        {
            "type": "about:blank",
            "title": "dependency_unavailable",
            "status": 503,
            "code": "dependency_unavailable",
            "detail": "服務依賴暫時無法使用",
            "request_id": uuid.uuid4().hex,
        },
        status_code=503,
    )


@app.middleware("http")
async def private_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    if getattr(request.state, "crawl_warning", False):
        response.headers["X-Crawl-Warning"] = "slow-down"
    return response

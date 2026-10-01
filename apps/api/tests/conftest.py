import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from fixture_lock import acquire

fixture_lock = None


def pytest_sessionstart(session):
    global fixture_lock
    fixture_lock = acquire()


def pytest_sessionfinish(session, exitstatus):
    if fixture_lock:
        fixture_lock.close()


# Dedicated disposable database only; never truncate a configured product database.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/mianshiya_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
os.environ["WEB_ORIGIN"] = "http://localhost:3000"
os.environ["ELASTICSEARCH_INDEX"] = "mianshiya-test-questions-" + uuid.uuid4().hex[:12]
if not os.environ["DATABASE_URL"].split("?", 1)[0].endswith("/mianshiya_test"):
    raise RuntimeError("Tests require the isolated mianshiya_test database")
if not os.environ["REDIS_URL"].endswith("/15"):
    raise RuntimeError("Tests require isolated Redis DB 15")

import pytest_asyncio
from mianshiya import policies, search
from mianshiya.db import Base, engine
from mianshiya.security import redis
from sqlalchemy import text


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def migrated_schema():
    # The guards above and process lock restrict this reset to the disposable fixture.
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", "upgrade", "head", cwd=Path(__file__).resolve().parents[1]
    )
    assert await asyncio.wait_for(process.wait(), timeout=120) == 0
    yield
    await search.es.close()
    await redis.aclose()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean(migrated_schema, request):
    async with engine.begin() as connection:
        names = ", ".join(table.name for table in Base.metadata.sorted_tables)
        await connection.execute(text("TRUNCATE " + names + " RESTART IDENTITY CASCADE"))
    await redis.flushdb()
    policies.loaded_at = 0
    policies.local_banks.clear()
    policies.local_limits.clear()
    if request.node.get_closest_marker("elasticsearch"):
        # A document delete retains external-version tombstones. A fresh concrete
        # index is required when this disposable SQL fixture restarts its IDs.
        await clear_search_fixture()
        search.es_circuit.success()
    yield
    if request.node.get_closest_marker("elasticsearch"):
        await clear_search_fixture()


async def clear_search_fixture():
    assert search.ALIAS.startswith("mianshiya-test-questions-")
    indices = await search.es.indices.get(
        index=search.ALIAS + "-*", ignore_unavailable=True, allow_no_indices=True
    )
    names = list(indices)
    assert all(name.startswith(search.ALIAS + "-") for name in names)
    if names:
        # Keep Elasticsearch's destructive-requires-name protection enabled.
        await search.es.indices.delete(index=names)

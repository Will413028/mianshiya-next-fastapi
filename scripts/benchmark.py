"""Fixed corpus, bounded concurrency, three cold/hot runs against real PG/Redis/ES."""

import asyncio
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/mianshiya_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
os.environ["ELASTICSEARCH_INDEX"] = "mianshiya-benchmark-questions"
if not os.environ["DATABASE_URL"].split("?", 1)[0].endswith("/mianshiya_test") or not os.environ[
    "REDIS_URL"
].endswith("/15"):
    raise SystemExit("Dedicated test database and Redis DB 15 required")
sys.path.insert(0, str(root / "apps/api"))
import httpx
from mianshiya import policies, search
from mianshiya.db import (
    MAX_OVERFLOW,
    POOL_SIZE,
    Bank,
    Base,
    Policy,
    Question,
    Relation,
    Session,
    User,
    engine,
)
from mianshiya.main import app
from mianshiya.security import passwords, redis
from sqlalchemy import event, insert, text

peak = checked = connections = 0


@event.listens_for(engine.sync_engine, "connect")
def connected(*unused):
    global connections
    connections += 1


@event.listens_for(engine.sync_engine, "checkout")
def checkout(*unused):
    global checked, peak
    checked += 1
    peak = max(peak, checked)


@event.listens_for(engine.sync_engine, "checkin")
def checkin(*unused):
    global checked
    checked -= 1


async def fixture():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await connection.execute(text("TRUNCATE " + names + " RESTART IDENTITY CASCADE"))
    password_hash = passwords.hash("disabled-benchmark-account")
    users = [
        {
            "account": "bench-" + str(i),
            "account_display": "bench-" + str(i),
            "password_hash": password_hash,
            "name": "學習者 " + str(i),
            "role": "user",
            "profile": {},
        }
        for i in range(1000)
    ]
    async with Session() as session:
        await session.execute(insert(User), users)
        await session.execute(
            insert(Bank),
            [
                {"title": "題庫 " + str(i), "description": "固定效能資料", "creator_id": 1}
                for i in range(100)
            ],
        )
        questions = [
            {
                "title": "資料庫交易練習 " + str(i),
                "content": "解釋交易、索引與一致性。" * 10,
                "answer": "使用資料庫約束與原子操作。" * 20,
                "tags": ["database", "benchmark"],
                "creator_id": i % 1000 + 1,
                "review_status": "approved",
                "version": 1,
            }
            for i in range(10000)
        ]
        await session.execute(insert(Question), questions)
        await session.execute(
            insert(Relation),
            [{"bank_id": i % 100 + 1, "question_id": i + 1, "creator_id": 1} for i in range(10000)],
        )
        for name, value in {
            "rate": {"requests": 10000, "window_seconds": 60, "hot_requests": 10000},
            "crawl": {
                "warning_reads": 9000,
                "max_reads": 10000,
                "window_seconds": 60,
                "cooldown_seconds": 60,
            },
        }.items():
            session.add(Policy(name=name, value=value, updated_by=1))
        await session.commit()
    await redis.flushdb()
    await search.ensure_index()
    rebuilt = await search.rebuild_index()
    return {
        "users": 1000,
        "banks": 100,
        "questions": 10000,
        "relations": 10000,
        "sha256": hashlib.sha256(
            json.dumps(questions, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "rebuild": rebuilt,
    }


async def run(mode):
    connections_before = connections
    load_before = os.getloadavg()
    for key in policies.cache_stats:
        policies.cache_stats[key] = 0
    async with Session() as session:
        row = await session.scalar(
            __import__("sqlalchemy").select(Policy).where(Policy.name == "cache")
        )
        value = {
            "hot_threshold": 10000 if mode == "cold" else 1,
            "window_seconds": 60,
            "ttl_seconds": 5,
            "local_ttl_seconds": 1,
        }
        if row:
            row.value = value
            row.version += 1
        else:
            session.add(Policy(name="cache", value=value, updated_by=1))
        await session.commit()
    await redis.flushdb()
    policies.loaded_at = 0
    policies.local_banks.clear()
    samples = {"detail": [], "bank": [], "search": []}
    errors = {}
    end = time.monotonic() + 60
    paths = [
        ("detail", "/api/v1/questions/1"),
        ("bank", "/api/v1/banks/1"),
        ("search", "/api/v1/questions/search?q=交易&bank_id=1"),
    ]

    async def load(worker):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://benchmark", timeout=10
        ) as client:
            i = worker
            while time.monotonic() < end:
                name, path = paths[i % 3]
                start = time.perf_counter()
                try:
                    response = await client.get(path)
                    if response.status_code == 200:
                        samples[name].append((time.perf_counter() - start) * 1000)
                    else:
                        code = str(response.status_code)
                        errors[code] = errors.get(code, 0) + 1
                except Exception as error:
                    code = type(error).__name__
                    errors[code] = errors.get(code, 0) + 1
                i += 1
                await asyncio.sleep(0.06)

    await asyncio.gather(*[load(i) for i in range(20)])
    result = {
        "mode": mode,
        "seconds": 60,
        "concurrency": 20,
        "think_time_ms": 60,
        "errors": errors,
        "metrics": {},
        "cache": dict(policies.cache_stats),
        "connections_created": connections - connections_before,
        "host_load_before": load_before,
        "host_load_after": os.getloadavg(),
    }
    for name, values in samples.items():
        ordered = sorted(values)
        result["metrics"][name] = {
            "requests": len(values),
            "p50_ms": round(statistics.median(values), 2) if values else None,
            "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2) if values else None,
        }
    return result


async def main():
    report = {
        "scope": "real API/PG/Redis/ES; ASGI transport excludes Next/network latency",
        "host": {
            "machine": platform.machine(),
            "cpu": os.cpu_count(),
            "python": platform.python_version(),
        },
        "fixture": await fixture(),
        "runs": [],
    }
    for mode in ("cold", "hot"):
        for index in range(3):
            result = await run(mode)
            report["runs"].append(result)
            print(
                mode + " run " + str(index + 1) + ": " + json.dumps(result["metrics"]), flush=True
            )
    report["pool"] = {
        "configured_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
        "peak_checked_out": peak,
        "connections_created": connections,
    }
    report["passed"] = all(
        not r["errors"]
        and r["metrics"]["detail"]["p95_ms"] is not None
        and r["metrics"]["detail"]["p95_ms"] <= 300
        and r["metrics"]["search"]["p95_ms"] is not None
        and r["metrics"]["search"]["p95_ms"] <= 500
        for r in report["runs"]
    )
    path = root / "reports/benchmark.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    await search.es.close()
    await redis.aclose()
    await engine.dispose()
    if not report["passed"]:
        raise SystemExit("Benchmark thresholds not met; inspect the report")


if __name__ == "__main__":
    from fixture_lock import acquire

    with acquire():
        asyncio.run(main())

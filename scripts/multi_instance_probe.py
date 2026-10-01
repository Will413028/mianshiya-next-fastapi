"""Run two real API processes against the same isolated PostgreSQL and Redis."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from fixture_lock import acquire

root = Path(__file__).resolve().parents[1]
database = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/mianshiya_test"
)
redis_url = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
if not database.split("?", 1)[0].endswith("/mianshiya_test") or not redis_url.endswith("/15"):
    raise SystemExit("Multi-instance probe requires the isolated integration fixture")
os.environ.update(DATABASE_URL=database, REDIS_URL=redis_url, WEB_ORIGIN="http://localhost:3000")
sys.path.insert(0, str(root / "apps/api"))
from mianshiya.db import Policy, Session, User, engine
from sqlalchemy import select, text


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def ready(client, process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned API process exited before readiness")
        try:
            response = await client.get("/api/v1/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError("Owned API readiness timed out")


async def main():
    processes, logs = [], []
    report = {
        "scope": "two real uvicorn processes sharing real PostgreSQL and Redis",
        "checks": {},
        "passed": False,
    }
    try:
        addresses = []
        for index in range(2):
            selected = port()
            log = (root / f"reports/multi-instance-{index}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "mianshiya.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(selected),
                        "--no-access-log",
                        "--no-proxy-headers",
                    ],
                    cwd=root / "apps/api",
                    env=os.environ.copy(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
            addresses.append("http://127.0.0.1:" + str(selected))
        headers = {"Origin": "http://localhost:3000"}
        async with (
            httpx.AsyncClient(base_url=addresses[0], headers=headers, timeout=10) as a,
            httpx.AsyncClient(base_url=addresses[1], headers=headers, timeout=10) as b,
        ):
            await asyncio.gather(ready(a, processes[0]), ready(b, processes[1]))
            suffix = uuid.uuid4().hex[:12]
            password = "integration-example-password"
            body = {"account": "race-" + suffix, "password": password, "confirmation": password}
            responses = await asyncio.gather(
                a.post("/api/v1/auth/register", json=body),
                b.post("/api/v1/auth/register", json=body),
            )
            assert sorted(response.status_code for response in responses) == [201, 409]
            async with Session() as session:
                people = (
                    await session.scalars(select(User).where(User.account == body["account"]))
                ).all()
                assert len(people) == 1
                learner_id = str(people[0].id)
                report["postgresql_version"] = await session.scalar(text("SHOW server_version_num"))
            report["checks"]["cross_process_registration_unique"] = True
            response = await b.post(
                "/api/v1/auth/sessions", json={"account": body["account"], "password": password}
            )
            assert response.status_code == 200
            admin_body = {**body, "account": "admin-" + suffix}
            assert (await a.post("/api/v1/auth/register", json=admin_body)).status_code == 201
            async with Session() as session:
                admin = await session.scalar(
                    select(User).where(User.account == admin_body["account"])
                )
                admin.role = "admin"
                await session.commit()
            response = await a.post(
                "/api/v1/auth/sessions",
                json={"account": admin_body["account"], "password": password},
            )
            assert response.status_code == 200
            a.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            assert (
                await a.patch("/api/v1/admin/users/" + learner_id, json={"role": "ban"})
            ).status_code == 200
            assert (await b.get("/api/v1/auth/session")).status_code == 401
            report["checks"]["cross_process_ban_revokes_session"] = True
            previous_rate = (await a.get("/api/v1/admin/policies/rate")).json()
            try:
                assert (
                    await a.patch(
                        "/api/v1/admin/policies/rate",
                        json={
                            "version": previous_rate["version"],
                            "value": {"requests": 10, "window_seconds": 60, "hot_requests": 10},
                        },
                    )
                ).status_code == 200
                from mianshiya.security import redis

                await redis.delete("rate:127.0.0.1:/api/v1/banks")
                await asyncio.sleep(1.1)
                responses = await asyncio.gather(
                    *[(a if index % 2 else b).get("/api/v1/banks") for index in range(24)]
                )
                assert sum(response.status_code == 200 for response in responses) == 10
                assert sum(response.status_code == 429 for response in responses) == 14
                assert all(
                    int(response.headers["Retry-After"]) > 0
                    for response in responses
                    if response.status_code == 429
                )
                report["checks"]["cross_process_atomic_rate_budget"] = True
            finally:
                await restore_policy("rate", previous_rate)
            response = await a.get("/api/v1/admin/policies/ip")
            assert response.status_code == 200
            previous = response.json()
            try:
                assert (
                    await a.patch(
                        "/api/v1/admin/policies/ip",
                        json={
                            "version": previous["version"],
                            "value": {"blacklist": ["127.0.0.1"], "whitelist": []},
                        },
                    )
                ).status_code == 200
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    response = await b.get("/api/v1/health")
                    if response.status_code == 403:
                        break
                    await asyncio.sleep(0.1)
                assert response.status_code == 403
                report["checks"]["cross_process_dynamic_ip_policy"] = True
                assert (
                    await b.get(
                        "/api/v1/health",
                        headers={
                            "X-Forwarded-For": "203.0.113.99",
                            "Forwarded": "for=203.0.113.99",
                        },
                    )
                ).status_code == 403
                report["checks"]["wire_forwarded_headers_cannot_spoof_peer"] = True
                processes[1].terminate()
                await asyncio.to_thread(processes[1].wait, timeout=30)
                processes[1] = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "mianshiya.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        addresses[1].rsplit(":", 1)[1],
                        "--no-access-log",
                        "--no-proxy-headers",
                    ],
                    cwd=root / "apps/api",
                    env=os.environ.copy(),
                    stdout=logs[1],
                    stderr=subprocess.STDOUT,
                )
                deadline = time.monotonic() + 60
                response = None
                while time.monotonic() < deadline:
                    assert processes[1].poll() is None
                    try:
                        response = await b.get("/api/v1/health")
                        if response.status_code == 403:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.2)
                assert response is not None and response.status_code == 403
                report["checks"]["restarted_instance_reloads_persisted_ip_policy"] = True
            finally:
                await restore_policy("ip", previous)
        report["passed"] = True
        print("Multi-instance probe: passed")
    finally:
        (root / "reports/multi-instance.json").write_text(json.dumps(report, indent=2) + "\n")
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
        for log in logs:
            log.close()
        await engine.dispose()


async def restore_policy(name, previous):
    async with Session() as session:
        row = await session.scalar(select(Policy).where(Policy.name == name).with_for_update())
        if row:
            if previous["version"] == 0:
                await session.delete(row)
            else:
                row.value, row.version = previous["value"], row.version + 1
            await session.commit()


if __name__ == "__main__":
    with acquire():
        asyncio.run(main())

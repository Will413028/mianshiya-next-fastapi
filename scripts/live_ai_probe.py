"""Actual API + worker + local provider product journey on the isolated fixture."""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
from fixture_lock import acquire
from multi_instance_probe import port, ready, root

os.environ["ELASTICSEARCH_INDEX"] = "mianshiya-live-ai-questions"

from mianshiya.db import Question, Session, User, engine
from sqlalchemy import select, text


async def main():
    started = time.monotonic()
    report = {
        "scope": "actual API and worker processes with real local provider",
        "provider": "local-openai-compatible",
        "model": os.environ.get("AI_MODEL", "qwen3:0.6b"),
        "paid_api_cost": 0,
        "checks": {},
        "samples": {},
    }
    selected = port()
    processes, logs = [], []
    try:
        for name, command in (
            (
                "api",
                [
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
            ),
            ("worker", ["-m", "mianshiya.search"]),
        ):
            log = (root / f"reports/live-ai-{name}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [sys.executable, *command],
                    cwd=root / "apps/api",
                    env=os.environ.copy(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{selected}",
            headers={"Origin": "http://localhost:3000"},
            timeout=150,
        ) as client:
            await ready(client, processes[0])
            account = "live-ai-" + uuid.uuid4().hex[:12]
            password = "integration-example-password"
            response = await client.post(
                "/api/v1/auth/register",
                json={"account": account, "password": password, "confirmation": password},
            )
            assert response.status_code == 201
            person = response.json()
            async with Session() as session:
                owner = await session.get(User, int(person["id"]))
                owner.role = "admin"
                report["postgresql_version"] = await session.scalar(text("SHOW server_version_num"))
                await session.commit()
            response = await client.post(
                "/api/v1/auth/sessions", json={"account": account, "password": password}
            )
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            for count in (1, 20):
                response = await client.post(
                    "/api/v1/admin/question-generation-jobs",
                    json={
                        "request_id": uuid.uuid4().hex,
                        "direction": "PostgreSQL 基礎，每題題幹及答案簡潔",
                        "count": count,
                    },
                )
                assert response.status_code == 202
                job_id = response.json()["id"]
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    response = await client.get("/api/v1/admin/question-generation-jobs/" + job_id)
                    assert response.status_code == 200
                    job = response.json()
                    if job["state"] in {"completed", "failed"}:
                        break
                    assert processes[1].poll() is None, "Owned worker exited"
                    await asyncio.sleep(0.5)
                assert job["state"] == "completed", "Live generation failed or timed out"
                assert len(job["result"]) == count
                async with Session() as session:
                    rows = (
                        await session.scalars(
                            select(Question).where(
                                Question.id.in_([int(value) for value in job["result"]])
                            )
                        )
                    ).all()
                    assert len(rows) == count and all(
                        row.review_status == "pending" for row in rows
                    )
                    report["samples"][f"generation_{count}"] = [
                        {
                            "title": row.title,
                            "content": row.content,
                            "answer": row.answer,
                            "tags": row.tags,
                        }
                        for row in rows
                    ]
                report["checks"][f"generation_exact_{count}_pending_review"] = True
            response = await client.post(
                "/api/v1/interviews",
                json={
                    "position": "PostgreSQL 初階工程師",
                    "experience": "初階",
                    "difficulty": "easy",
                },
            )
            assert response.status_code == 201
            meeting = response.json()["id"]
            for event, message, state in (
                ("start", "", "ACTIVE"),
                ("chat", "我會使用 transaction 與 UNIQUE constraint 保護資料一致性。", "ACTIVE"),
                ("end", "", "ENDED"),
            ):
                body = {"event": event, "event_id": uuid.uuid4().hex, "message": message}
                response = await client.post(f"/api/v1/interviews/{meeting}/events", json=body)
                assert response.status_code == 200, "Live interview event failed"
                interview = response.json()
                assert interview["status"] == state and interview["pending"] is False
                assert interview["history"][-1]["content"].strip()
                replay = await client.post(f"/api/v1/interviews/{meeting}/events", json=body)
                assert replay.status_code == 200 and replay.json() == interview
                report["checks"][f"interview_{event}_and_replay"] = True
            assert len(interview["history"]) == 6
            report["samples"]["interview"] = interview["history"]
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error_type"] = type(error).__name__
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (root / "reports/live-ai.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=10)
        for log in logs:
            log.close()
        await engine.dispose()


if __name__ == "__main__":
    with acquire():
        asyncio.run(main())

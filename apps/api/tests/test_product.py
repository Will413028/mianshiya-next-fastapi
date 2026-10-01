import asyncio
from datetime import datetime

import httpx
import pytest
from mianshiya import ai
from mianshiya.content import mark_activity
from mianshiya.db import Outbox, Question, Session, User
from mianshiya.main import app
from mianshiya.security import Bloom, passwords, redis
from sqlalchemy import select

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "http://localhost:3000"


def client(agent="desktop"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, "User-Agent": agent},
    )


async def account(c, name="learner-one", role="user"):
    password = "integration-example-password"
    response = await c.post(
        "/api/v1/auth/register",
        json={"account": name, "password": password, "confirmation": password},
    )
    assert response.status_code == 201
    if role != "user":
        async with Session() as session:
            row = await session.scalar(select(User).where(User.account == name))
            row.role = role
            await session.commit()
    response = await c.post("/api/v1/auth/sessions", json={"account": name, "password": password})
    assert response.status_code == 200
    c.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


async def material(c):
    bank = await c.post(
        "/api/v1/banks", json={"title": "資料庫題庫", "description": "交易與一致性"}
    )
    question = await c.post(
        "/api/v1/questions",
        json={
            "title": "交易如何避免重複帳號",
            "content": "並行註冊",
            "answer": "UNIQUE constraint",
            "tags": ["database", "python"],
        },
    )
    assert bank.status_code == 201 and question.status_code == 201
    return bank.json(), question.json()


async def test_registration_database_unique_and_password():
    async with client() as a, client() as b:
        body = {
            "account": "same-account",
            "password": "integration-example-password",
            "confirmation": "integration-example-password",
        }
        responses = await asyncio.gather(
            a.post("/api/v1/auth/register", json=body), b.post("/api/v1/auth/register", json=body)
        )
        assert sorted(r.status_code for r in responses) == [201, 409]
        async with Session() as session:
            rows = (await session.scalars(select(User))).all()
            assert len(rows) == 1
            assert rows[0].password_hash.startswith("$argon2id$")
            assert passwords.verify(rows[0].password_hash, body["password"])
        assert "password" not in responses[0].text


async def test_auth_csrf_revocation_device_and_unknown_fields():
    async with client() as a, client() as b, client("iPhone mobile") as mobile:
        await account(a)
        r = await a.patch("/api/v1/users/me", json={"name": "更新"})
        assert r.status_code == 200
        csrf = a.headers.pop("X-CSRF-Token")
        assert (await a.patch("/api/v1/users/me", json={"name": "拒絕"})).status_code == 403
        a.headers["X-CSRF-Token"] = csrf
        assert (await a.get("/api/v1/users?surprise=1")).status_code == 422
        assert (
            await a.post("/api/v1/questions", json={"title": "越權", "role": "admin"})
        ).status_code in {403, 422}
        body = {"account": "learner-one", "password": "integration-example-password"}
        assert (await mobile.post("/api/v1/auth/sessions", json=body)).status_code == 200
        assert (await a.get("/api/v1/auth/session")).status_code == 200
        assert (await b.post("/api/v1/auth/sessions", json=body)).status_code == 200
        assert (await a.get("/api/v1/auth/session")).status_code == 401
        assert (await mobile.get("/api/v1/auth/session")).status_code == 200
        b.headers["X-CSRF-Token"] = (await b.get("/api/v1/auth/session")).json()["csrf_token"]
        assert (await b.delete("/api/v1/auth/session")).status_code == 204
        assert (await b.get("/api/v1/auth/session")).status_code == 401


async def test_crud_relations_atomic_batch_and_deletion():
    async with client() as c:
        await account(c, role="admin")
        bank, question = await material(c)
        invalid = await c.post(
            "/api/v1/banks/" + bank["id"] + "/questions/batch",
            json={"ids": [question["id"], "999999"]},
        )
        assert invalid.status_code == 422
        assert (await c.get("/api/v1/bank-question-relations")).json()["total"] == 0
        added = await c.post(
            "/api/v1/banks/" + bank["id"] + "/questions/batch",
            json={"ids": [question["id"], question["id"]]},
        )
        assert added.json() == {"requested": 1, "inserted": 1, "skipped": 0}
        again = await c.post(
            "/api/v1/banks/" + bank["id"] + "/questions/batch", json={"ids": [question["id"]]}
        )
        assert again.json()["skipped"] == 1
        relation = (await c.get("/api/v1/bank-question-relations")).json()["items"][0]
        assert (await c.get("/api/v1/bank-question-relations/" + relation["id"])).status_code == 200
        removed = await c.request(
            "DELETE",
            "/api/v1/banks/" + bank["id"] + "/questions/batch",
            json={"ids": [question["id"]]},
        )
        assert removed.status_code == 200 and removed.json()["removed"] == 1
        assert (
            await c.post(
                "/api/v1/bank-question-relations",
                json={"bank_id": bank["id"], "question_id": question["id"]},
            )
        ).status_code == 201
        assert (await c.delete("/api/v1/questions/" + question["id"])).status_code == 204
        assert (await c.get("/api/v1/questions/" + question["id"])).status_code == 404
        assert (await c.get("/api/v1/bank-question-relations")).json()["total"] == 0
        async with Session() as session:
            events = (await session.scalars(select(Outbox))).all()
            assert any(e.kind == "question" and e.version > 1 for e in events)


async def test_owner_isolation_and_public_profile():
    async with client() as a, client() as b:
        await account(a, "admin-one", "admin")
        bank, question = await material(a)
        person = await account(b, "second-person")
        assert (
            await b.patch("/api/v1/banks/" + bank["id"], json={"title": "偷改"})
        ).status_code == 403
        assert (
            await b.patch("/api/v1/questions/" + question["id"], json={"title": "偷改"})
        ).status_code == 403
        await b.patch(
            "/api/v1/users/me",
            json={"name": "學生", "phone": "private", "email": "private@example.test"},
        )
        public = (await a.get("/api/v1/users/" + person["id"])).json()
        assert "phone" not in public and "email" not in public and "account" not in public


async def test_bitmap_timezone_leapday_and_idempotence():
    async with client() as c:
        user = await account(c)
        for stamp in (
            "2026-12-31T15:59:59+00:00",
            "2026-12-31T16:00:00+00:00",
            "2028-02-28T16:00:00+00:00",
        ):
            await mark_activity(user["id"], datetime.fromisoformat(stamp))
            await mark_activity(user["id"], datetime.fromisoformat(stamp))
        for year, day in ((2026, "2026-12-31"), (2027, "2027-01-01"), (2028, "2028-02-29")):
            response = await c.get("/api/v1/users/me/activity?year=" + str(year))
            assert response.json()["dates"] == [day]
            assert await redis.ttl("activity:" + user["id"] + ":" + str(year)) == -1


async def test_interview_owner_state_idempotence_and_concurrency(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    block = False

    async def reply(messages, schema=None):
        if block:
            entered.set()
            await release.wait()
        return "請解釋交易的原子性。"

    monkeypatch.setattr(ai, "completion", reply)
    async with client() as owner, client() as stranger:
        await account(owner, "interview-owner")
        await account(stranger, "interview-stranger")
        interview = (await owner.post("/api/v1/interviews", json={"position": "後端工程師"})).json()
        path = "/api/v1/interviews/" + interview["id"]
        assert (await stranger.get(path)).status_code == 403
        assert (
            await stranger.post(path + "/events", json={"event_id": "x", "event": "start"})
        ).status_code == 403
        assert (
            await owner.post(
                path + "/events", json={"event_id": "x", "event": "chat", "message": "尚未開始"}
            )
        ).status_code == 409
        body = {"event_id": "start-1", "event": "start"}
        start = await owner.post(path + "/events", json=body)
        assert start.status_code == 200 and start.json()["status"] == "ACTIVE"
        assert (await owner.post(path + "/events", json=body)).json() == start.json()
        assert (
            await owner.post(path + "/events", json={"event_id": "start-2", "event": "start"})
        ).status_code == 409
        block = True
        first = asyncio.create_task(
            owner.post(
                path + "/events",
                json={"event_id": "chat-0", "event": "chat", "message": "我的回答"},
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=60)
        try:
            overlapping = await owner.post(
                path + "/events",
                json={"event_id": "chat-1", "event": "chat", "message": "我的回答"},
            )
            assert overlapping.status_code == 409
        finally:
            release.set()
            completed = await first
        assert completed.status_code == 200
        block = False
        assert len((await owner.get(path)).json()["history"]) == 4
        end = await owner.post(path + "/events", json={"event_id": "end", "event": "end"})
        assert end.json()["status"] == "ENDED"
        assert (
            await owner.post(path + "/events", json={"event_id": "invalid", "event": "unknown"})
        ).status_code == 422


async def test_generation_wrong_count_writes_nothing_then_retry(monkeypatch):
    async def wrong(messages, schema=None):
        return '{"questions":[]}'

    monkeypatch.setattr(ai, "completion", wrong)
    async with client() as c:
        await account(c, role="admin")
        body = {"request_id": "generation-1", "direction": "Python", "count": 1}
        response = await c.post("/api/v1/admin/question-generation-jobs", json=body)
        assert response.status_code == 202
        assert await ai.run_generation()
        async with Session() as session:
            assert (await session.scalars(select(Question))).all() == []
        job = (
            await c.get("/api/v1/admin/question-generation-jobs/" + response.json()["id"])
        ).json()
        assert job["state"] == "failed"

        async def valid(messages, schema=None):
            return '{"questions":[{"title":"Python list","content":"如何使用 list？","answer":"使用可變序列","tags":["Python"]}]}'

        monkeypatch.setattr(ai, "completion", valid)
        await c.post("/api/v1/admin/question-generation-jobs", json=body)
        await ai.run_generation()
        job = (
            await c.get("/api/v1/admin/question-generation-jobs/" + response.json()["id"])
        ).json()
        assert job["state"] == "completed" and len(job["result"]) == 1
        assert (await c.get("/api/v1/questions")).json()["total"] == 0
        assert (await c.get("/api/v1/admin/questions")).json()["total"] == 1


async def test_dynamic_policies_bloom_and_revocation():
    bloom = Bloom(["192.0.2.1"])
    assert bloom.contains("192.0.2.1") and not bloom.contains("192.0.2.2")
    bloom.bits[:] = bytes([255]) * len(bloom.bits)
    assert not bloom.contains("192.0.2.2")
    async with client() as c, client() as victim:
        await account(c, "admin-policy", "admin")
        user = await account(victim, "victim-person")
        rule = {"requests": 100, "window_seconds": 60, "hot_requests": 50}
        assert (
            await c.patch("/api/v1/admin/policies/rate", json={"version": 0, "value": rule})
        ).status_code == 200
        assert (
            await c.patch("/api/v1/admin/policies/rate", json={"version": 0, "value": rule})
        ).status_code == 409
        assert (
            await c.patch("/api/v1/admin/users/" + user["id"], json={"role": "ban"})
        ).status_code == 200
        assert (await victim.get("/api/v1/auth/session")).status_code == 401

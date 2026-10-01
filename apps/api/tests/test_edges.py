from datetime import datetime, timezone

import pytest
from mianshiya import ai, policies
from mianshiya.db import Interview, Question, Relation, Session
from mianshiya.security import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from test_product import account, client, material

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_navigation_crosses_page_boundary_and_excludes_unpublished():
    async with client() as c:
        user = await account(c, role="admin")
        bank, _ = await material(c)
        async with Session() as session:
            # IDs exceed JavaScript's safe integer range; API must keep decimal strings.
            ids = [9007199254741000 + index for index in range(22)]
            await session.execute(
                text("SELECT setval(pg_get_serial_sequence('questions', 'id'), :first_id, false)"),
                {"first_id": ids[0]},
            )
            for index, value in enumerate(ids):
                session.add(
                    Question(
                        title=f"題目 {index}",
                        content="題幹",
                        answer="題解",
                        tags=[],
                        creator_id=int(user["id"]),
                        review_status="approved",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    )
                )
            await session.flush()
            session.add_all(
                Relation(bank_id=int(bank["id"]), question_id=value, creator_id=int(user["id"]))
                for value in ids
            )
            await session.commit()
        # Stable descending ID order: the twentieth item points into page two.
        response = await c.get(f"/api/v1/banks/{bank['id']}/questions/{ids[2]}/navigation")
        assert response.status_code == 200
        assert response.json() == {"previous_id": str(ids[3]), "next_id": str(ids[1]), "page": 1}
        response = await c.get(f"/api/v1/banks/{bank['id']}/questions/{ids[1]}/navigation")
        assert response.json() == {"previous_id": str(ids[2]), "next_id": str(ids[0]), "page": 2}
        assert (await c.get(f"/api/v1/questions/{ids[0]}")).json()["id"] == str(ids[0])
        assert (await c.get(f"/api/v1/questions/0{ids[0]}")).status_code == 422
        assert (await c.get(f"/api/v1/questions/{2**63}")).status_code == 422


async def test_cached_bank_obeys_sql_version_and_immediate_deletion():
    async with client() as c:
        await account(c, role="admin")
        bank, _ = await material(c)
        # Seed a realistic stale shared and process-local projection.
        import json

        await redis.set("cache:bank:" + bank["id"], json.dumps(bank), ex=5)
        assert (await c.get("/api/v1/banks/" + bank["id"])).json()["title"] == bank["title"]
        assert bank["id"] in policies.local_banks
        assert (
            await c.patch("/api/v1/banks/" + bank["id"], json={"title": "新版題庫"})
        ).status_code == 200
        assert (await c.get("/api/v1/banks/" + bank["id"])).json()["title"] == "新版題庫"
        assert (await c.delete("/api/v1/banks/" + bank["id"])).status_code == 204
        assert (await c.get("/api/v1/banks/" + bank["id"])).status_code == 404


async def test_redis_outage_fails_auth_closed_with_sanitized_problem(monkeypatch):
    async with client() as c:
        await account(c)

        async def unavailable(*args, **kwargs):
            raise RedisConnectionError("credential-containing diagnostics must stay private")

        monkeypatch.setattr(redis, "get", unavailable)
        response = await c.get("/api/v1/auth/session")
        assert response.status_code == 503
        assert "credential-containing" not in response.text
        assert "request_id" in response.json()


async def test_cross_origin_mutations_are_rejected():
    async with client() as c:
        await account(c)
        c.headers["Origin"] = "https://untrusted.example"
        assert (await c.patch("/api/v1/users/me", json={"name": "跨來源"})).status_code == 403
        assert (await c.delete("/api/v1/auth/session")).status_code == 403


async def test_admin_user_profile_crud_keeps_private_fields():
    async with client() as admin, client() as learner:
        await account(admin, "profile-admin", "admin")
        password = "integration-example-password"
        response = await admin.post(
            "/api/v1/admin/users",
            json={
                "account": "managed-learner",
                "password": password,
                "confirmation": password,
                "name": "受管理學員",
                "avatar_url": "https://example.test/avatar.png",
                "bio": "初始簡介",
            },
        )
        assert response.status_code == 201
        value = response.json()["id"]
        login = await learner.post(
            "/api/v1/auth/sessions", json={"account": "managed-learner", "password": password}
        )
        assert login.status_code == 200
        learner.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (
            await learner.patch("/api/v1/users/me", json={"name": "學員", "phone": "private-phone"})
        ).status_code == 200
        assert (
            await admin.patch(
                "/api/v1/admin/users/" + value,
                json={"avatar_url": "https://example.test/new.png", "bio": "新簡介"},
            )
        ).status_code == 200
        person = (await admin.get("/api/v1/admin/users/" + value)).json()
        assert person["phone"] == "private-phone" and person["bio"] == "新簡介"
        assert (await admin.get("/api/v1/users/" + value)).json()[
            "avatar_url"
        ] == "https://example.test/new.png"
        assert "phone" not in (await admin.get("/api/v1/users/" + value)).json()
        assert (await admin.delete("/api/v1/admin/users/" + value)).status_code == 204
        assert (await learner.get("/api/v1/auth/session")).status_code == 401


async def test_deleted_interview_cannot_be_resurrected_by_pending_provider(monkeypatch):
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(messages, schema=None):
        entered.set()
        await release.wait()
        return "不應寫回的延遲答案"

    monkeypatch.setattr(ai, "completion", reply)
    async with client() as c:
        await account(c)
        response = await c.post("/api/v1/interviews", json={"position": "後端工程師"})
        value = response.json()["id"]
        path = "/api/v1/interviews/" + value
        pending = asyncio.create_task(
            c.post(path + "/events", json={"event_id": "start-pending", "event": "start"})
        )
        await asyncio.wait_for(entered.wait(), timeout=60)
        try:
            # Must complete while the external provider is still waiting: no SQL lock leak.
            assert (await asyncio.wait_for(c.delete(path), timeout=60)).status_code == 204
        finally:
            release.set()
            finished = await pending
        assert finished.status_code == 404
        async with Session() as session:
            row = await session.get(Interview, int(value))
            assert row.deleted_at and row.history == [] and row.pending_event_id is None


async def test_history_and_context_limits_reserve_end_and_preserve_messages(monkeypatch):
    async def reply(messages, schema=None):
        return "面試總結：請繼續練習交易隔離。"

    monkeypatch.setattr(ai, "completion", reply)
    async with client() as c:
        await account(c)
        for scenario in ("rounds", "context"):
            response = await c.post("/api/v1/interviews", json={"position": "後端工程師"})
            value = response.json()["id"]
            history = (
                [{"role": "user", "content": "回答"}, {"role": "assistant", "content": "問題"}] * 99
                if scenario == "rounds"
                else [
                    {"role": "user", "content": "a" * 12500},
                    {"role": "assistant", "content": "問題"},
                ]
            )
            async with Session() as session:
                row = await session.get(Interview, int(value))
                row.status, row.history = "ACTIVE", history
                await session.commit()
            path = "/api/v1/interviews/" + value
            chat = await c.post(
                path + "/events", json={"event_id": "chat", "event": "chat", "message": "新回答"}
            )
            assert chat.status_code == 409
            assert chat.json()["code"] == (
                "history_limit" if scenario == "rounds" else "context_limit"
            )
            preserved = (await c.get(path)).json()
            assert preserved["history"] == history and preserved["pending"] is False
            end = await c.post(path + "/events", json={"event_id": "end", "event": "end"})
            assert end.status_code == 200 and end.json()["status"] == "ENDED"
            assert end.json()["history"][: len(history)] == history
            assert len(end.json()["history"]) <= 200

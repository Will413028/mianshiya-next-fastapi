import pytest
from mianshiya import search
from mianshiya.db import Outbox, Session
from sqlalchemy import select
from test_product import account, client, material

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.elasticsearch]


async def drain():
    async with Session() as session:
        remaining = len(
            (await session.scalars(select(Outbox).where(Outbox.status != "done"))).all()
        )
    for _ in range(remaining + 2):
        await search.process_outbox()
    await search.es.indices.refresh(index=search.ALIAS)


async def test_actual_chinese_search_membership_tags_and_tombstone():
    await search.ensure_index()
    async with client() as c:
        await account(c, role="admin")
        bank, question = await material(c)
        second_bank = (await c.post("/api/v1/banks", json={"title": "另一個題庫"})).json()
        second = (
            await c.post(
                "/api/v1/questions",
                json={
                    "title": "資料庫交易隔離",
                    "content": "事務隔離",
                    "answer": "snapshot",
                    "tags": ["database"],
                },
            )
        ).json()
        await c.post(
            "/api/v1/banks/" + bank["id"] + "/questions/batch", json={"ids": [question["id"]]}
        )
        await c.post(
            "/api/v1/banks/" + second_bank["id"] + "/questions/batch", json={"ids": [second["id"]]}
        )
        await drain()
        result = await c.get(
            "/api/v1/questions/search",
            params={"q": "交易", "bank_id": bank["id"], "tags": ["database", "python"]},
        )
        assert result.status_code == 200
        assert {q["id"] for q in result.json()["items"]} == {question["id"]}
        other = await c.get(
            "/api/v1/questions/search", params={"q": "交易", "bank_id": second_bank["id"]}
        )
        assert {q["id"] for q in other.json()["items"]} == {second["id"]}
        before = await search.es.get(index=search.ALIAS, id=question["id"])
        assert (await c.delete("/api/v1/questions/" + question["id"])).status_code == 204
        immediate = await c.get(
            "/api/v1/questions/search", params={"q": "交易", "bank_id": bank["id"]}
        )
        assert immediate.json()["items"] == []
        await drain()
        from elasticsearch import ConflictError

        with pytest.raises(ConflictError):
            await search.es.index(
                index=search.ALIAS,
                id=question["id"],
                document=before["_source"],
                version=before["_version"],
                version_type="external_gte",
            )
        assert (await search.es.get(index=search.ALIAS, id=question["id"]))["_source"][
            "deleted"
        ] is True
        rebuild = await search.rebuild_index()
        assert rebuild["documents"] == 2
        result = await c.get("/api/v1/questions/search", params={"q": "交易"})
        assert {q["id"] for q in result.json()["items"]} == {second["id"]}

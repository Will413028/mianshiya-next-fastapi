import asyncio
import os
import uuid
from datetime import timedelta

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import Circuit, ProviderUnavailable, run_generation
from .content import question_view, with_authors
from .db import Bank, Outbox, Question, Relation, Session, User, db, engine
from .schemas import PageView, QuestionView
from .security import admin, fail, identity, now, redis

es = AsyncElasticsearch(
    os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:59200"), request_timeout=5, max_retries=0
)
ALIAS = os.environ.get("ELASTICSEARCH_INDEX", "mianshiya-questions")
es_circuit = Circuit()
router = APIRouter(prefix="/api/v1", tags=["search"])
MAPPING = {
    "properties": {
        "id": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "cjk"},
        "content": {"type": "text", "analyzer": "cjk"},
        "answer": {"type": "text", "analyzer": "cjk"},
        "tags": {"type": "keyword"},
        "bank_ids": {"type": "keyword"},
        "creator_id": {"type": "keyword"},
        "deleted": {"type": "boolean"},
        "create_time": {"type": "date"},
        "update_time": {"type": "date"},
    }
}


async def ensure_index():
    if not await es.indices.exists_alias(name=ALIAS):
        name = ALIAS + "-initial"
        if not await es.indices.exists(index=name):
            await es.indices.create(index=name, mappings=MAPPING)
        try:
            await es.indices.update_aliases(
                actions=[{"add": {"index": name, "alias": ALIAS, "is_write_index": True}}]
            )
        except Exception:
            if not await es.indices.exists_alias(name=ALIAS):
                raise


async def document(session, row):
    banks = (
        await session.scalars(
            select(Relation.bank_id)
            .join(Bank, Bank.id == Relation.bank_id)
            .where(Relation.question_id == row.id, Bank.deleted_at.is_(None))
        )
    ).all()
    return {
        **question_view(row),
        "bank_ids": [str(v) for v in banks],
        "deleted": row.deleted_at is not None or row.review_status != "approved",
        "create_time": row.created_at.isoformat(),
        "update_time": row.updated_at.isoformat(),
    }


async def index_question(session, row, index=ALIAS):
    from elasticsearch import ConflictError

    try:
        await es.index(
            index=index,
            id=str(row.id),
            document=await document(session, row),
            version=row.version,
            version_type="external_gte",
        )
    except ConflictError:
        # A later aggregate version is already present, including a durable tombstone.
        pass


async def bulk_snapshot(session, rows, index):
    for offset in range(0, len(rows), 500):
        batch = rows[offset : offset + 500]
        pairs = (
            await session.execute(
                select(Relation.question_id, Relation.bank_id)
                .join(Bank, Bank.id == Relation.bank_id)
                .where(Relation.question_id.in_([q.id for q in batch]), Bank.deleted_at.is_(None))
            )
        ).all()
        memberships = {}
        for question_id, bank_id in pairs:
            memberships.setdefault(question_id, []).append(str(bank_id))
        actions = []
        for row in batch:
            source = {
                **question_view(row),
                "bank_ids": memberships.get(row.id, []),
                "deleted": row.deleted_at is not None or row.review_status != "approved",
                "create_time": row.created_at.isoformat(),
                "update_time": row.updated_at.isoformat(),
            }
            actions.append(
                {
                    "_op_type": "index",
                    "_index": index,
                    "_id": str(row.id),
                    "_version": row.version,
                    "_version_type": "external_gte",
                    "_source": source,
                }
            )
        _, errors = await async_bulk(es, actions, raise_on_error=False, chunk_size=500)
        if any(next(iter(error.values())).get("status") != 409 for error in errors):
            raise ProviderUnavailable("rebuild_bulk_failed")


async def process_outbox():
    async with Session() as session:
        event = await session.scalar(
            select(Outbox)
            .where(
                ((Outbox.status == "pending") & (Outbox.available_at <= now()))
                | ((Outbox.status == "processing") & (Outbox.lease_until < now()))
            )
            .order_by(Outbox.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not event:
            return False
        event.status, event.lease_until = "processing", now() + timedelta(seconds=30)
        event.attempts += 1
        value, lease, kind, aggregate_id, attempts = (
            event.id,
            event.lease_until,
            event.kind,
            event.aggregate_id,
            event.attempts,
        )
        await session.commit()
    try:
        async with Session() as source:
            if kind == "question":
                row = await source.get(Question, aggregate_id)
                if row:
                    await ensure_index()
                    await index_question(source, row)
            elif kind == "bank_invalidate":
                await redis.delete(f"cache:bank:{aggregate_id}")
            elif kind == "user_cleanup":
                async for key in redis.scan_iter(match=f"activity:{aggregate_id}:*", count=100):
                    await redis.delete(key)
                async for key in redis.scan_iter(
                    match=f"activity:read:{aggregate_id}:*", count=100
                ):
                    await redis.delete(key)
    except Exception:
        async with Session() as retry:
            event = await retry.get(Outbox, value, with_for_update=True)
            if event.status == "processing" and event.lease_until == lease:
                event.status, event.lease_until = "pending", None
                event.available_at = now() + timedelta(seconds=min(60, 2 ** min(attempts, 6)))
                await retry.commit()
        return True
    async with Session() as finish:
        event = await finish.get(Outbox, value, with_for_update=True)
        if event.status == "processing" and event.lease_until == lease:
            event.status, event.lease_until = "done", None
            await finish.commit()
    return True


@router.get(
    "/questions/search", response_model=PageView[QuestionView], operation_id="searchQuestions"
)
async def search_questions(
    q: str = "",
    page: int = 1,
    page_size: int = 20,
    tags: list[str] = Query(default=[]),
    bank_id: str | None = None,
    creator_id: str | None = None,
    id: str | None = None,
    not_id: str | None = None,
    sort: str = "relevance",
    session: AsyncSession = Depends(db),
):
    if page < 1 or not 1 <= page_size <= 20 or page * page_size > 10000:
        fail(422, "invalid_pagination")
    sorts = {
        "relevance": [{"_score": "desc"}, {"id": "asc"}],
        "create_time": [{"create_time": "desc"}, {"id": "asc"}],
        "update_time": [{"update_time": "desc"}, {"id": "asc"}],
        "id": [{"id": "asc"}],
    }
    if sort not in sorts:
        fail(422, "invalid_sort")
    filters = [{"term": {"deleted": False}}, *[{"term": {"tags": tag}} for tag in tags]]
    for field, val in (("bank_ids", bank_id), ("creator_id", creator_id), ("id", id)):
        if val:
            identity(val)
            filters.append({"term": {field: val}})
    excluded = [{"term": {"id": str(identity(not_id))}}] if not_id else []
    must = (
        [
            {
                "multi_match": {
                    "query": q,
                    "fields": ["title^3", "content", "answer"],
                    "operator": "or",
                }
            }
        ]
        if q
        else [{"match_all": {}}]
    )
    try:
        es_circuit.enter()
        result = await es.search(
            index=ALIAS,
            query={"bool": {"must": must, "filter": filters, "must_not": excluded}},
            sort=sorts[sort],
            from_=(page - 1) * page_size,
            size=page_size,
            track_total_hits=True,
        )
        es_circuit.success()
    except Exception:
        es_circuit.failure()
        fail(503, "search_unavailable")
    hits = [int(hit["_id"]) for hit in result["hits"]["hits"]]
    stmt = select(Question).where(
        Question.id.in_(hits), Question.deleted_at.is_(None), Question.review_status == "approved"
    )
    # Canonical filters also suppress stale relation/tag updates before the index catches up.
    if bank_id:
        stmt = stmt.where(
            Question.id.in_(
                select(Relation.question_id)
                .join(Bank)
                .where(Relation.bank_id == identity(bank_id), Bank.deleted_at.is_(None))
            )
        )
    if creator_id:
        stmt = stmt.where(Question.creator_id == identity(creator_id))
    for tag in tags:
        stmt = stmt.where(Question.tags.contains([tag]))
    rows = {row.id: row for row in (await session.scalars(stmt)).all()}
    items = await with_authors(
        session, [question_view(rows[value]) for value in hits if value in rows]
    )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": result["hits"]["total"]["value"],
    }


async def rebuild_index():
    """Serialize rebuild with a PostgreSQL advisory lock and fence writers at the switch."""
    from sqlalchemy import text

    name = ALIAS + "-" + uuid.uuid4().hex
    async with (
        asyncio.timeout(120),
        engine.connect() as connection,
        Session(bind=connection) as session,
    ):
        acquired = await session.scalar(text("SELECT pg_try_advisory_lock(901781)"))
        if not acquired:
            fail(409, "rebuild_in_progress")
        try:
            await es.indices.create(index=name, mappings=MAPPING)
            # Maintenance rebuild: canonical reconciliation holds a write fence.
            # The bounded bulk protocol and deadline are measured in acceptance.
            await session.rollback()
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            rows = (await session.scalars(select(Question).order_by(Question.id))).all()
            await bulk_snapshot(session, rows, name)
            await session.commit()
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.execute(
                text("LOCK TABLE question_banks, questions, question_bank_questions IN SHARE MODE")
            )
            session.expire_all()
            rows = (await session.scalars(select(Question).order_by(Question.id))).all()
            await bulk_snapshot(session, rows, name)
            await es.indices.refresh(index=name)
            aliases = (
                await es.indices.get_alias(name=ALIAS)
                if await es.indices.exists_alias(name=ALIAS)
                else {}
            )
            actions = [{"remove": {"index": old, "alias": ALIAS}} for old in aliases]
            actions.append({"add": {"index": name, "alias": ALIAS, "is_write_index": True}})
            await es.indices.update_aliases(actions=actions)
            await session.commit()
        finally:
            await session.rollback()
            await session.execute(text("SELECT pg_advisory_unlock(901781)"))
            await session.commit()
    return {"index": name, "documents": len(rows)}


@router.post("/admin/search/rebuild", operation_id="rebuildSearch")
async def rebuild(user: User = Depends(admin)):
    try:
        return await rebuild_index()
    except HTTPException:
        raise
    except Exception:
        fail(503, "rebuild_failed")


@router.get("/admin/worker/status", operation_id="getWorkerStatus")
async def worker_status(user: User = Depends(admin), session: AsyncSession = Depends(db)):
    from sqlalchemy import func

    rows = (
        await session.execute(
            select(Outbox.status, func.count(), func.min(Outbox.created_at)).group_by(Outbox.status)
        )
    ).all()
    return {
        "outbox": [
            {"status": status, "count": count, "oldest": oldest.isoformat() if oldest else None}
            for status, count, oldest in rows
        ]
    }


async def outbox_loop():
    while True:
        try:
            worked = await process_outbox()
            if not worked:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(2)


async def generation_loop():
    while True:
        try:
            if not await run_generation():
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(2)


async def worker():
    async with asyncio.TaskGroup() as group:
        group.create_task(outbox_loop())
        group.create_task(generation_loop())


if __name__ == "__main__":
    asyncio.run(worker())

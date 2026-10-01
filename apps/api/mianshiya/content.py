import calendar
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import queries
from .db import Bank, Outbox, Question, Relation, User, db
from .schemas import (
    BankDetailView,
    BankInput,
    BankView,
    Batch,
    Input,
    NavigationView,
    PageView,
    QuestionInput,
    QuestionView,
    RelationInput,
)
from .security import (
    COOKIE,
    active,
    admin,
    current_user,
    fail,
    identity,
    now,
    owner,
    public_user,
    redis,
)

router = APIRouter(prefix="/api/v1", tags=["content"])


def bank_view(row):
    return {
        key: str(getattr(row, key)) if key in {"id", "creator_id"} else getattr(row, key)
        for key in BankView.model_fields
        if key != "author"
    }


def question_view(row):
    return {
        key: str(getattr(row, key)) if key in {"id", "creator_id"} else getattr(row, key)
        for key in QuestionView.model_fields
        if key != "author"
    }


async def with_authors(session, items):
    creator_ids = {identity(item["creator_id"]) for item in items}
    if not creator_ids:
        return items
    authors = {
        str(row.id): public_user(row)
        for row in await session.scalars(select(User).where(User.id.in_(creator_ids)))
    }
    return [{**item, "author": authors[item["creator_id"]]} for item in items]


async def authored(session, item):
    return (await with_authors(session, [item]))[0]


def relation_view(row):
    return {
        "id": str(row.id),
        "bank_id": str(row.bank_id),
        "question_id": str(row.question_id),
        "creator_id": str(row.creator_id),
    }


async def changed(session, question):
    question.version += 1
    session.add(
        Outbox(aggregate_id=question.id, version=question.version, kind="question", payload={})
    )


async def bank_changed(session, bank):
    bank.version += 1
    session.add(
        Outbox(aggregate_id=bank.id, version=bank.version, kind="bank_invalidate", payload={})
    )


async def page_rows(
    session, model, filters, page, page_size, serializer, admin_scope=False, order=None
):
    if page < 1 or not 1 <= page_size <= (100 if admin_scope else 20):
        fail(422, "invalid_pagination")
    total = await session.scalar(select(func.count()).select_from(model).where(*filters))
    rows = (
        await session.scalars(
            select(model)
            .where(*filters)
            .order_by(*(order or [model.created_at.desc(), model.id.desc()]))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [serializer(row) for row in rows]
    if model in (Bank, Question):
        items = await with_authors(session, items)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/banks", response_model=PageView[BankView], operation_id="listBanks")
async def list_banks(
    query: queries.PageQuery = Depends(queries.banks), session: AsyncSession = Depends(db)
):
    return await page_rows(
        session,
        Bank,
        query.filters,
        query.page,
        query.page_size,
        bank_view,
        order=query.order(Bank, {"title": Bank.title}),
    )


@router.get("/users/me/banks", operation_id="listMyBanks")
async def my_banks(
    query: queries.PageQuery = Depends(queries.banks),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Bank,
        [*query.filters, Bank.creator_id == user.id],
        query.page,
        query.page_size,
        bank_view,
        order=query.order(Bank, {"title": Bank.title}),
    )


@router.get("/banks/{value}", response_model=BankDetailView, operation_id="getBank")
async def get_bank(
    value: str,
    include_questions: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=20),
    session: AsyncSession = Depends(db),
):
    from .policies import cached_bank

    result = dict(await cached_bank(value, session))
    if include_questions:
        linked = select(Relation.question_id).where(Relation.bank_id == identity(value))
        result["question_page"] = await page_rows(
            session,
            Question,
            [
                Question.id.in_(linked),
                Question.deleted_at.is_(None),
                Question.review_status == "approved",
            ],
            page,
            page_size,
            question_view,
        )
    return result


@router.post("/banks", response_model=BankView, status_code=201, operation_id="createBank")
async def create_bank(
    body: BankInput, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    row = Bank(**body.model_dump(exclude={"version"}), creator_id=user.id)
    session.add(row)
    await session.flush()
    session.add(Outbox(aggregate_id=row.id, version=1, kind="bank_invalidate", payload={}))
    await session.commit()
    return await authored(session, bank_view(row))


@router.patch("/banks/{value}", response_model=BankView, operation_id="updateBank")
async def update_bank(
    value: str,
    body: BankInput,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    row = await active(session, Bank, value, True)
    owner(row, user)
    if body.version is not None and body.version != row.version:
        fail(409, "version_conflict")
    for key, val in body.model_dump(exclude={"version"}).items():
        setattr(row, key, val)
    await bank_changed(session, row)
    await session.commit()
    return await authored(session, bank_view(row))


@router.delete("/banks/{value}", status_code=204, operation_id="deleteBank")
async def delete_bank(
    value: str, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = await active(session, Bank, value, True)
    owner(row, user)
    question_ids = (
        await session.scalars(select(Relation.question_id).where(Relation.bank_id == row.id))
    ).all()
    questions = (
        await session.scalars(
            select(Question)
            .where(Question.id.in_(question_ids))
            .order_by(Question.id)
            .with_for_update()
        )
    ).all()
    await session.execute(delete(Relation).where(Relation.bank_id == row.id))
    row.deleted_at = now()
    await bank_changed(session, row)
    for question in questions:
        await changed(session, question)
    await session.commit()


@router.get("/questions", response_model=PageView[QuestionView], operation_id="listQuestions")
async def list_questions(
    query: queries.PageQuery = Depends(queries.questions), session: AsyncSession = Depends(db)
):
    return await page_rows(
        session,
        Question,
        [*query.filters, Question.review_status == "approved"],
        query.page,
        query.page_size,
        question_view,
        order=query.order(Question, {"title": Question.title}),
    )


@router.get(
    "/admin/questions", response_model=PageView[QuestionView], operation_id="listAdminQuestions"
)
async def admin_questions(
    query: queries.PageQuery = Depends(queries.questions),
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Question,
        query.filters,
        query.page,
        query.page_size,
        question_view,
        True,
        query.order(Question, {"title": Question.title}),
    )


@router.get("/admin/banks", response_model=PageView[BankView], operation_id="listAdminBanks")
async def admin_banks(
    query: queries.PageQuery = Depends(queries.banks),
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Bank,
        query.filters,
        query.page,
        query.page_size,
        bank_view,
        True,
        query.order(Bank, {"title": Bank.title}),
    )


@router.get("/users/me/questions", operation_id="listMyQuestions")
async def my_questions(
    query: queries.PageQuery = Depends(queries.questions),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Question,
        [*query.filters, Question.creator_id == user.id],
        query.page,
        query.page_size,
        question_view,
        order=query.order(Question, {"title": Question.title}),
    )


async def mark_activity(user_id, instant=None):
    local = (instant or now()).astimezone(ZoneInfo("Asia/Taipei"))
    try:
        await redis.setbit(f"activity:{user_id}:{local.year}", local.timetuple().tm_yday - 1, 1)
    except RedisError:
        fail(503, "activity_unavailable")


@router.get("/questions/{value}", response_model=QuestionView, operation_id="getQuestion")
async def get_question(value: str, request: Request, session: AsyncSession = Depends(db)):
    found = (
        await session.execute(
            select(Question, User)
            .join(User, User.id == Question.creator_id)
            .where(Question.id == identity(value), Question.deleted_at.is_(None))
        )
    ).one_or_none()
    if found is None:
        fail(404, "not_found")
    row, author = found
    user = await current_user(request, session) if request.cookies.get(COOKIE) else None
    if row.review_status != "approved" and (not user or user.role != "admin"):
        fail(404, "not_found")
    if user:
        await mark_activity(user.id)
        await redis.set(f"activity:read:{user.id}:{row.id}", "1", ex=300)
    return {**question_view(row), "author": public_user(author)}


@router.post(
    "/questions", response_model=QuestionView, status_code=201, operation_id="createQuestion"
)
async def create_question(
    body: QuestionInput, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    row = Question(**body.model_dump(exclude={"version"}), creator_id=user.id)
    session.add(row)
    await session.flush()
    session.add(Outbox(aggregate_id=row.id, version=1, kind="question", payload={}))
    await session.commit()
    return await authored(session, question_view(row))


@router.patch("/questions/{value}", response_model=QuestionView, operation_id="updateQuestion")
async def update_question(
    value: str,
    body: QuestionInput,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    row = await active(session, Question, value, True)
    owner(row, user)
    if body.version is not None and row.version != body.version:
        fail(409, "version_conflict")
    for key, val in body.model_dump(exclude={"version"}).items():
        setattr(row, key, val)
    await changed(session, row)
    await session.commit()
    return await authored(session, question_view(row))


async def remove_question(session, row):
    row.deleted_at = now()
    await session.execute(delete(Relation).where(Relation.question_id == row.id))
    await changed(session, row)


@router.delete("/questions/{value}", status_code=204, operation_id="deleteQuestion")
async def delete_question(
    value: str, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = await active(session, Question, value, True)
    owner(row, user)
    await remove_question(session, row)
    await session.commit()


@router.post("/questions/batch-delete", operation_id="batchDeleteQuestions")
async def batch_delete(
    body: Batch, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    ids = sorted({identity(value) for value in body.ids})
    rows = (
        await session.scalars(
            select(Question).where(Question.id.in_(ids)).order_by(Question.id).with_for_update()
        )
    ).all()
    if len(rows) != len(ids):
        fail(422, "unknown_question")
    count = 0
    for row in rows:
        if row.deleted_at is None:
            await remove_question(session, row)
            count += 1
    await session.commit()
    return {"requested": len(ids), "deleted": count, "skipped": len(ids) - count}


async def validate_pair(session, body, lock=False):
    bank = await active(session, Bank, body.bank_id, lock)
    question = await active(session, Question, body.question_id, lock)
    return bank, question


@router.post("/bank-question-relations", status_code=201, operation_id="createRelation")
async def create_relation(
    body: RelationInput, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    bank, question = await validate_pair(session, body, True)
    stmt = (
        insert(Relation)
        .values(bank_id=bank.id, question_id=question.id, creator_id=user.id)
        .on_conflict_do_nothing()
        .returning(Relation.id)
    )
    value = await session.scalar(stmt)
    if value is None:
        fail(409, "relation_exists")
    await changed(session, question)
    await session.commit()
    return relation_view(await session.get(Relation, value))


@router.get("/bank-question-relations", operation_id="listPublicRelations")
async def relations(
    query: queries.PageQuery = Depends(queries.relations), session: AsyncSession = Depends(db)
):
    filters = [
        Relation.bank_id.in_(select(Bank.id).where(Bank.deleted_at.is_(None))),
        Relation.question_id.in_(
            select(Question.id).where(
                Question.deleted_at.is_(None), Question.review_status == "approved"
            )
        ),
    ]
    return await page_rows(
        session,
        Relation,
        [*filters, *query.filters],
        query.page,
        query.page_size,
        relation_view,
        order=query.order(Relation),
    )


@router.get("/users/me/bank-question-relations", operation_id="listMyRelations")
async def my_relations(
    query: queries.PageQuery = Depends(queries.relations),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Relation,
        [*query.filters, Relation.creator_id == user.id],
        query.page,
        query.page_size,
        relation_view,
        order=query.order(Relation),
    )


@router.get("/admin/bank-question-relations", operation_id="listRelations")
async def admin_relations(
    query: queries.PageQuery = Depends(queries.relations),
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    return await page_rows(
        session,
        Relation,
        query.filters,
        query.page,
        query.page_size,
        relation_view,
        True,
        query.order(Relation),
    )


@router.get("/bank-question-relations/{value}", operation_id="getRelation")
async def get_relation(value: str, session: AsyncSession = Depends(db)):
    row = await active(session, Relation, value)
    await active(session, Bank, str(row.bank_id))
    question = await active(session, Question, str(row.question_id))
    if question.review_status != "approved":
        fail(404, "not_found")
    return relation_view(row)


@router.patch("/bank-question-relations/{value}", operation_id="updateRelation")
async def update_relation(
    value: str,
    body: RelationInput,
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    row = await active(session, Relation, value, True)
    old = await active(session, Question, str(row.question_id), True)
    bank, question = await validate_pair(session, body, True)
    duplicate = await session.scalar(
        select(Relation.id).where(
            Relation.bank_id == bank.id, Relation.question_id == question.id, Relation.id != row.id
        )
    )
    if duplicate:
        fail(409, "relation_exists")
    row.bank_id, row.question_id = bank.id, question.id
    await changed(session, old)
    if old.id != question.id:
        await changed(session, question)
    await session.commit()
    return relation_view(row)


@router.delete("/bank-question-relations/{value}", status_code=204, operation_id="deleteRelation")
async def delete_relation(
    value: str, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = await active(session, Relation, value, True)
    owner(row, user)
    question = await active(session, Question, str(row.question_id), True)
    await session.delete(row)
    await changed(session, question)
    await session.commit()


async def batch_relations(bank_id, body, session, user, remove):
    bank = await active(session, Bank, bank_id, True)
    ids = sorted({identity(value) for value in body.ids})
    questions = (
        await session.scalars(
            select(Question).where(Question.id.in_(ids)).order_by(Question.id).with_for_update()
        )
    ).all()
    if len(questions) != len(ids) or (not remove and any(q.deleted_at for q in questions)):
        fail(422, "unknown_question")
    if remove:
        result = await session.execute(
            delete(Relation)
            .where(Relation.bank_id == bank.id, Relation.question_id.in_(ids))
            .returning(Relation.id)
        )
        count = len(result.all())
    else:
        result = await session.execute(
            insert(Relation)
            .values(
                [
                    {"bank_id": bank.id, "question_id": q.id, "creator_id": user.id}
                    for q in questions
                ]
            )
            .on_conflict_do_nothing()
            .returning(Relation.id)
        )
        count = len(result.all())
    for question in questions:
        await changed(session, question)
    await session.commit()
    return {
        "requested": len(ids),
        "removed" if remove else "inserted": count,
        "skipped": len(ids) - count,
    }


@router.post("/banks/{bank_id}/questions/batch", operation_id="addBankQuestions")
async def add_batch(
    bank_id: str, body: Batch, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    return await batch_relations(bank_id, body, session, user, False)


@router.delete("/banks/{bank_id}/questions/batch", operation_id="removeBankQuestions")
async def remove_batch(
    bank_id: str, body: Batch, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    return await batch_relations(bank_id, body, session, user, True)


class ActivityInput(Input):
    question_id: str


@router.post("/users/me/activity", operation_id="recordActivity")
async def record_activity(
    body: ActivityInput, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = await active(session, Question, body.question_id)
    if not await redis.get(f"activity:read:{user.id}:{row.id}"):
        fail(409, "successful_read_required")
    await mark_activity(user.id)
    return {"date": now().astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()}


@router.get("/users/me/activity", operation_id="getActivity")
async def get_activity(year: int = 2026, user: User = Depends(current_user)):
    if not 1970 <= year <= 2100:
        fail(422, "invalid_year")
    count = 366 if calendar.isleap(year) else 365
    pipe = redis.pipeline()
    for offset in range(count):
        pipe.getbit(f"activity:{user.id}:{year}", offset)
    bits = await pipe.execute()
    first = date(year, 1, 1).toordinal()
    return {
        "year": year,
        "dates": [date.fromordinal(first + i).isoformat() for i, bit in enumerate(bits) if bit],
    }


@router.delete(
    "/banks/{bank_id}/questions/{question_id}", status_code=204, operation_id="removeBankQuestion"
)
async def remove_pair(
    bank_id: str,
    question_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    bank = await active(session, Bank, bank_id, True)
    owner(bank, user)
    question = await active(session, Question, question_id, True)
    await session.execute(
        delete(Relation).where(Relation.bank_id == bank.id, Relation.question_id == question.id)
    )
    await changed(session, question)
    await session.commit()


@router.get(
    "/banks/{bank_id}/questions/{question_id}/navigation",
    response_model=NavigationView,
    operation_id="getBankQuestionNavigation",
)
async def navigation(bank_id: str, question_id: str, session: AsyncSession = Depends(db)):
    bank = await active(session, Bank, bank_id)
    order = [Question.created_at.desc(), Question.id.desc()]
    window = (
        select(
            Question.id,
            func.lag(Question.id).over(order_by=order).label("previous_id"),
            func.lead(Question.id).over(order_by=order).label("next_id"),
            func.row_number().over(order_by=order).label("ordinal"),
        )
        .join(Relation, Relation.question_id == Question.id)
        .where(
            Relation.bank_id == bank.id,
            Question.deleted_at.is_(None),
            Question.review_status == "approved",
        )
        .subquery()
    )
    row = (
        await session.execute(select(window).where(window.c.id == identity(question_id)))
    ).one_or_none()
    if not row:
        fail(404, "not_in_bank")
    return {
        "previous_id": str(row.previous_id) if row.previous_id else None,
        "next_id": str(row.next_id) if row.next_id else None,
        "page": (row.ordinal - 1) // 20 + 1,
    }

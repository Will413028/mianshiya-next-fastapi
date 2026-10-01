from dataclasses import dataclass, field
from typing import Literal

from fastapi import Depends, Query
from sqlalchemy import or_, select

from .db import Bank, Interview, Question, Relation, User
from .security import fail, identity


@dataclass
class PageQuery:
    page: int
    page_size: int
    sort: str
    direction: str
    filters: list = field(default_factory=list)
    q: str = ""

    def order(self, model, extra=None):
        allowed = {
            "create_time": model.created_at,
            "update_time": model.updated_at,
            "id": model.id,
            **(extra or {}),
        }
        if self.sort not in allowed:
            fail(422, "invalid_sort")
        column = allowed[self.sort]
        return [
            column.asc() if self.direction == "asc" else column.desc(),
            model.id.asc() if self.direction == "asc" else model.id.desc(),
        ]


def pagination(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = "create_time",
    order: Literal["asc", "desc"] = "desc",
):
    return PageQuery(page, page_size, sort, order)


def ids(query, model, id, not_id, creator_id=None, creator_column=None):
    if id is not None:
        query.filters.append(model.id == identity(id))
    if not_id is not None:
        query.filters.append(model.id != identity(not_id))
    if creator_id is not None:
        query.filters.append(
            (creator_column if creator_column is not None else model.creator_id)
            == identity(creator_id)
        )


def banks(
    query: PageQuery = Depends(pagination),
    q: str = "",
    title: str = "",
    description: str = "",
    picture_url: str | None = None,
    id: str | None = None,
    not_id: str | None = None,
    creator_id: str | None = None,
):
    query.filters.append(Bank.deleted_at.is_(None))
    if q:
        query.filters.append(or_(Bank.title.ilike(f"%{q}%"), Bank.description.ilike(f"%{q}%")))
    for column, value in ((Bank.title, title), (Bank.description, description)):
        if value:
            query.filters.append(column.ilike(f"%{value}%"))
    if picture_url is not None:
        query.filters.append(Bank.picture_url == picture_url)
    ids(query, Bank, id, not_id, creator_id)
    return query


def questions(
    query: PageQuery = Depends(pagination),
    q: str = "",
    title: str = "",
    content: str = "",
    answer: str = "",
    tags: list[str] = Query(default=[]),
    bank_id: str | None = None,
    creator_id: str | None = None,
    id: str | None = None,
    not_id: str | None = None,
    review_status: Literal["approved", "pending"] | None = None,
):
    query.filters.append(Question.deleted_at.is_(None))
    if q:
        query.filters.append(
            or_(
                Question.title.ilike(f"%{q}%"),
                Question.content.ilike(f"%{q}%"),
                Question.answer.ilike(f"%{q}%"),
            )
        )
    for column, value in (
        (Question.title, title),
        (Question.content, content),
        (Question.answer, answer),
    ):
        if value:
            query.filters.append(column.ilike(f"%{value}%"))
    for tag in tags:
        query.filters.append(Question.tags.contains([tag]))
    if bank_id is not None:
        query.filters.append(
            Question.id.in_(
                select(Relation.question_id)
                .join(Bank, Bank.id == Relation.bank_id)
                .where(Relation.bank_id == identity(bank_id), Bank.deleted_at.is_(None))
            )
        )
    if review_status is not None:
        query.filters.append(Question.review_status == review_status)
    ids(query, Question, id, not_id, creator_id)
    return query


def relations(
    query: PageQuery = Depends(pagination),
    bank_id: str | None = None,
    question_id: str | None = None,
    creator_id: str | None = None,
    id: str | None = None,
    not_id: str | None = None,
):
    for column, value in ((Relation.bank_id, bank_id), (Relation.question_id, question_id)):
        if value is not None:
            query.filters.append(column == identity(value))
    ids(query, Relation, id, not_id, creator_id)
    return query


def interviews(
    query: PageQuery = Depends(pagination),
    position: str = "",
    experience: str = "",
    difficulty: str = "",
    status: Literal["NOT_STARTED", "ACTIVE", "ENDED"] | None = None,
    owner_id: str | None = None,
    id: str | None = None,
    not_id: str | None = None,
):
    query.filters.append(Interview.deleted_at.is_(None))
    for column, value in (
        (Interview.position, position),
        (Interview.experience, experience),
        (Interview.difficulty, difficulty),
    ):
        if value:
            query.filters.append(column.ilike(f"%{value}%"))
    if status is not None:
        query.filters.append(Interview.status == status)
    ids(query, Interview, id, not_id, owner_id, Interview.owner_id)
    return query


def users(
    query: PageQuery = Depends(pagination),
    q: str = "",
    name: str = "",
    bio: str = "",
    role: Literal["user", "admin", "ban"] | None = None,
    id: str | None = None,
    not_id: str | None = None,
):
    query.filters.append(User.deleted_at.is_(None))
    if name:
        query.filters.append(User.name.ilike(f"%{name}%"))
    if bio:
        query.filters.append(User.profile["bio"].astext.ilike(f"%{bio}%"))
    if role is not None:
        query.filters.append(User.role == role)
    ids(query, User, id, not_id)
    # q differs by audience: private account search is added only by the admin router.
    query.q = q
    return query

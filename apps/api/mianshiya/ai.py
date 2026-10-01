import hashlib
import json
import os
import time
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import queries
from .db import GenerationJob, Interview, Outbox, Question, Session, User, db
from .schemas import EventInput, GenerationInput, InterviewInput, InterviewView, JobView, PageView
from .security import active, admin, current_user, fail, now

router = APIRouter(prefix="/api/v1", tags=["AI"])


class ProviderUnavailable(Exception):
    pass


class Circuit:
    def __init__(self, threshold=3, cooldown=30):
        self.failures = 0
        self.open_until = 0
        self.threshold, self.cooldown = threshold, cooldown
        self.probe = False

    def enter(self):
        if self.open_until > time.monotonic():
            raise ProviderUnavailable("circuit_open")
        if self.open_until:
            if self.probe:
                raise ProviderUnavailable("probe_in_progress")
            self.probe = True

    def success(self):
        self.failures, self.open_until, self.probe = 0, 0, False

    def failure(self):
        self.failures += 1
        self.probe = False
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooldown


ai_circuit = Circuit()
INPUT_BYTES = 16384
INTERVIEW_REPLY_BYTES = 4096


def input_size(messages):
    return sum(len(message["content"].encode("utf-8")) for message in messages)


async def completion(messages, schema=None):
    if len(messages) > 204 or input_size(messages) > INPUT_BYTES:
        raise ProviderUnavailable("provider_context_limit")
    ai_circuit.enter()
    payload = {
        "model": os.environ.get("AI_MODEL", "qwen3:0.6b"),
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 8192,
        "stream": False,
    }
    effort = os.environ.get("AI_REASONING_EFFORT", "none")
    if effort:
        payload["reasoning_effort"] = effort
    if schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "questions", "schema": schema, "strict": True},
        }
    # Values go directly to the provider; never report Authorization or configuration.
    key = os.environ.get("AI_API_KEY", "local")
    base = os.environ.get("AI_BASE_URL", "http://127.0.0.1:11439/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                base + "/chat/completions", json=payload, headers={"Authorization": "Bearer " + key}
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("incomplete response")
            value = choice["message"]["content"]
            if not isinstance(value, str) or not value.strip():
                raise ValueError("empty response")
        ai_circuit.success()
        return value
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        ai_circuit.failure()
        raise ProviderUnavailable("provider_unavailable") from None


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100000)
    answer: str = Field(min_length=1, max_length=100000)
    tags: list[str] = Field(max_length=20)


class GeneratedBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[GeneratedQuestion]


def job_view(row):
    return {
        "id": str(row.id),
        "request_id": row.request_id,
        "state": row.state,
        "input": row.input,
        "result": row.result,
        "error": row.error,
        "attempts": row.attempts,
    }


@router.post(
    "/admin/question-generation-jobs",
    status_code=202,
    response_model=JobView,
    operation_id="generateQuestions",
)
async def generate(
    body: GenerationInput, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    existing = await session.scalar(
        select(GenerationJob).where(GenerationJob.request_id == body.request_id).with_for_update()
    )
    values = body.model_dump(exclude={"request_id"})
    if existing:
        if existing.input != values or existing.owner_id != user.id:
            fail(409, "idempotency_conflict")
        if existing.state == "failed":
            existing.state, existing.error = "pending", None
            await session.commit()
        return job_view(existing)
    row = GenerationJob(request_id=body.request_id, owner_id=user.id, input=values)
    session.add(row)
    await session.commit()
    return job_view(row)


@router.get(
    "/admin/question-generation-jobs/{value}",
    response_model=JobView,
    operation_id="getGenerationJob",
)
async def get_job(value: str, user: User = Depends(admin), session: AsyncSession = Depends(db)):
    return job_view(await active(session, GenerationJob, value))


async def run_generation():
    async with Session() as session:
        row = await session.scalar(
            select(GenerationJob)
            .where(
                (GenerationJob.state == "pending")
                | ((GenerationJob.state == "running") & (GenerationJob.lease_until < now()))
            )
            .order_by(GenerationJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return False
        row.state, row.lease_until = "running", now() + timedelta(seconds=150)
        row.attempts += 1
        job_id, lease, values, owner_id = row.id, row.lease_until, row.input, row.owner_id
        await session.commit()
    try:
        schema = GeneratedBatch.model_json_schema()
        schema["properties"]["questions"].update(minItems=values["count"], maxItems=values["count"])
        text = await completion(
            [
                {
                    "role": "system",
                    "content": "你是面試題教材作者。產生原創題目及正確詳解，使用繁體中文。嚴格回傳指定 JSON，禁止 Markdown 圍欄。/no_think",
                },
                {
                    "role": "user",
                    "content": f"方向：{values['direction']}。精確產生 {values['count']} 題，包含 title/content/answer/tags。",
                },
            ],
            schema,
        )
        result = GeneratedBatch.model_validate_json(text)
        if len(result.questions) != values["count"]:
            raise ValueError("wrong count")
    except (ProviderUnavailable, ValidationError, ValueError):
        async with Session() as session:
            row = await session.get(GenerationJob, job_id, with_for_update=True)
            if row.state == "running" and row.lease_until == lease:
                row.state, row.error, row.lease_until = (
                    "failed",
                    "invalid_or_unavailable_provider",
                    None,
                )
                await session.commit()
        return True
    async with Session() as session:
        row = await session.get(GenerationJob, job_id, with_for_update=True)
        owner = await session.get(User, owner_id)
        if row.state != "running" or row.lease_until != lease:
            return True
        if not owner or owner.deleted_at or owner.role != "admin":
            row.state, row.error = "failed", "owner_unavailable"
        else:
            ids = []
            for item in result.questions:
                question = Question(
                    **item.model_dump(), creator_id=owner_id, review_status="pending"
                )
                session.add(question)
                await session.flush()
                ids.append(str(question.id))
                session.add(
                    Outbox(aggregate_id=question.id, version=1, kind="question", payload={})
                )
            row.state, row.result = "completed", ids
        row.lease_until = None
        await session.commit()
    return True


def interview_view(row):
    return {
        "id": str(row.id),
        "owner_id": str(row.owner_id),
        "position": row.position,
        "experience": row.experience,
        "difficulty": row.difficulty,
        "status": row.status,
        "history": row.history,
        "version": row.version,
        "pending": row.pending_event_id is not None,
    }


async def owned_interview(session, value, user, lock=False):
    row = await active(session, Interview, value, lock)
    if row.owner_id != user.id:
        fail(403, "interview_owner_required")
    return row


@router.post(
    "/interviews", status_code=201, response_model=InterviewView, operation_id="createInterview"
)
async def create_interview(
    body: InterviewInput, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = Interview(**body.model_dump(), owner_id=user.id)
    session.add(row)
    await session.commit()
    return interview_view(row)


@router.get("/interviews", response_model=PageView[InterviewView], operation_id="listMyInterviews")
async def list_interviews(
    query: queries.PageQuery = Depends(queries.interviews),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    from .content import page_rows

    return await page_rows(
        session,
        Interview,
        [*query.filters, Interview.owner_id == user.id],
        query.page,
        query.page_size,
        interview_view,
        order=query.order(Interview, {"position": Interview.position}),
    )


@router.get("/admin/interviews", operation_id="listInterviews")
async def list_admin_interviews(
    query: queries.PageQuery = Depends(queries.interviews),
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    from .content import page_rows

    return await page_rows(
        session,
        Interview,
        query.filters,
        query.page,
        query.page_size,
        interview_view,
        True,
        order=query.order(Interview, {"position": Interview.position}),
    )


@router.get("/interviews/{value}", response_model=InterviewView, operation_id="getInterview")
async def get_interview(
    value: str, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    return interview_view(await owned_interview(session, value, user))


@router.delete("/interviews/{value}", status_code=204, operation_id="deleteInterview")
async def delete_interview(
    value: str, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    row = await active(session, Interview, value, True)
    if row.owner_id != user.id and user.role != "admin":
        fail(403, "interview_owner_required")
    row.deleted_at, row.pending_event_id = now(), None
    row.version += 1
    await session.commit()


@router.post(
    "/interviews/{value}/events", response_model=InterviewView, operation_id="handleInterviewEvent"
)
async def interview_event(
    value: str,
    body: EventInput,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db),
):
    row = await owned_interview(session, value, user, True)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    recorded = row.events.get(body.event_id)
    if recorded:
        if recorded["digest"] != digest:
            fail(409, "idempotency_conflict")
        return {
            **interview_view(row),
            "history": row.history[: recorded["history_length"]],
            "status": recorded["status"],
            "version": recorded["version"],
            "pending": False,
        }
    if row.pending_event_id and row.lease_until and row.lease_until > now():
        fail(409, "event_in_progress")
    valid = (body.event == "start" and row.status == "NOT_STARTED") or (
        body.event in {"chat", "end"} and row.status == "ACTIVE"
    )
    if not valid:
        fail(409, "invalid_transition")
    if body.event == "chat" and not body.message.strip():
        fail(422, "message_required")
    if body.event == "chat" and (
        len(row.history) >= 198
        or len(json.dumps(row.history, ensure_ascii=False).encode()) + len(body.message.encode())
        > 1024 * 1024 - 65536
    ):
        fail(409, "history_limit")
    history = list(row.history)
    instruction = {
        "start": "直接提出一個符合此職位與難度的技術情境問題，等待回答。",
        "chat": "先針對候選人剛才的回答給簡短而具體的回饋，再提出一個相關的技術追問；不可重複上一題。",
        "end": "面試已結束，不再提問。根據這場對話給出 0 到 100 分的總評、優點、待改善項目與具體練習建議；沒有足夠證據時明確說明。",
    }[body.event]
    system = (
        f"你是技術面試官。候選人的職位已知為 {row.position}，年資 {row.experience}，難度 {row.difficulty}。"
        "不要再詢問職位或年資，不替候選人作答。全程使用繁體中文。" + instruction + "/no_think"
    )
    prompt = (
        "開始面試，先提出第一個問題。"
        if body.event == "start"
        else "結束面試，提供評分、優點、待改善項目與練習建議。"
        if body.event == "end"
        else body.message
    )
    messages = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": prompt},
    ]
    # Keep every persisted message and reserve room for the next answer and END.
    if input_size(messages) > INPUT_BYTES - INTERVIEW_REPLY_BYTES - 512 and body.event != "end":
        fail(409, "context_limit")
    if input_size(messages) > INPUT_BYTES:
        fail(409, "context_limit")
    row.pending_event_id, row.lease_until = body.event_id, now() + timedelta(seconds=150)
    row.version += 1
    reserved_version, row_id, owner_id = row.version, row.id, user.id
    await session.commit()
    try:
        answer = await completion(messages)
        if body.event != "end" and len(answer.encode("utf-8")) > INTERVIEW_REPLY_BYTES:
            raise ProviderUnavailable("provider_output_limit")
    except ProviderUnavailable:
        async with Session() as cleanup:
            item = await cleanup.get(Interview, row_id, with_for_update=True)
            if item and item.pending_event_id == body.event_id and item.version == reserved_version:
                item.pending_event_id, item.lease_until = None, None
                await cleanup.commit()
        fail(503, "provider_unavailable")
    # Separate transaction: no SQL lock held over the external call.
    await session.rollback()
    session.expire_all()
    item = await active(session, Interview, value, True)
    if item.owner_id != owner_id:
        fail(403, "interview_owner_required")
    author = await session.get(User, owner_id)
    if not author or author.deleted_at or author.role == "ban":
        fail(401, "session_revoked")
    if item.version != reserved_version or item.pending_event_id != body.event_id:
        fail(409, "event_superseded")
    updated = [
        *history,
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer},
    ]
    if len(json.dumps(updated, ensure_ascii=False).encode()) > 1024 * 1024:
        item.pending_event_id, item.lease_until = None, None
        await session.commit()
        fail(409, "history_limit")
    item.history, item.status = updated, "ENDED" if body.event == "end" else "ACTIVE"
    item.pending_event_id, item.lease_until = None, None
    item.version += 1
    response = interview_view(item)
    item.events = {
        **item.events,
        body.event_id: {
            "digest": digest,
            "history_length": len(updated),
            "status": item.status,
            "version": item.version,
        },
    }
    await session.commit()
    return response

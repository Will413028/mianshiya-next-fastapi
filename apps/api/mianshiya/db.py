import os
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def pool_configuration():
    try:
        size = int(os.environ.get("DB_POOL_SIZE", "10"))
        overflow = int(os.environ.get("DB_MAX_OVERFLOW", "0"))
        if not 1 <= size <= 20 or not 0 <= overflow <= 20 or size + overflow > 30:
            raise ValueError
    except ValueError:
        raise RuntimeError("Invalid bounded database pool configuration") from None
    return size, overflow


POOL_SIZE, MAX_OVERFLOW = pool_configuration()
engine = create_async_engine(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/mianshiya"),
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_timeout=5,
    connect_args={"connect_timeout": 5},
)
Session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Entity, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin', 'ban')", name="users_role_valid"),
        CheckConstraint("jsonb_typeof(profile) = 'object'", name="users_profile_object"),
    )
    account: Mapped[str] = mapped_column(String(256), unique=True)
    account_display: Mapped[str] = mapped_column(String(256))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user")
    name: Mapped[str] = mapped_column(String(100), default="學習者")
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bank(Entity, Base):
    __tablename__ = "question_banks"
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    picture_url: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Question(Entity, Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(tags) = 'array' AND NOT jsonb_path_exists(tags, '$[*] ? (@.type() != \"string\")')",
            name="questions_tags_strings",
        ),
        CheckConstraint("review_status IN ('approved', 'pending')", name="questions_review_valid"),
    )
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(20), default="approved")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Relation(Entity, Base):
    __tablename__ = "question_bank_questions"
    __table_args__ = (UniqueConstraint("bank_id", "question_id"),)
    bank_id: Mapped[int] = mapped_column(ForeignKey("question_banks.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Interview(Entity, Base):
    __tablename__ = "mock_interviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NOT_STARTED', 'ACTIVE', 'ENDED')", name="interviews_status_valid"
        ),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name="interviews_difficulty_valid"
        ),
        CheckConstraint("jsonb_typeof(history) = 'array'", name="interviews_history_array"),
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    position: Mapped[str] = mapped_column(String(200))
    experience: Mapped[str] = mapped_column(String(200))
    difficulty: Mapped[str] = mapped_column(String(20))
    history: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    pending_event_id: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GenerationJob(Entity, Base):
    __tablename__ = "ai_generation_jobs"
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(100), unique=True)
    input: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[list] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Outbox(Entity, Base):
    __tablename__ = "outbox_events"
    aggregate_id: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Policy(Entity, Base):
    __tablename__ = "dynamic_policies"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


async def db():
    async with Session() as session:
        yield session

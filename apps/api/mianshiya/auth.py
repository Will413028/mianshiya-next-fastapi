from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import queries
from .db import Interview, Outbox, User, db
from .schemas import AdminUser, AdminUserUpdate, Login, Profile, Register, SessionView, UserView
from .security import (
    COOKIE,
    active,
    admin,
    check_origin,
    check_password,
    create_session,
    current_user,
    fail,
    normalize,
    now,
    passwords,
    public_user,
    redis,
    revoke_user,
)

router = APIRouter(prefix="/api/v1", tags=["users"])


async def insert_user(body, session, role="user", name="學習者", profile=None):
    if body.password != body.confirmation:
        fail(422, "password_mismatch")
    user = User(
        account=normalize(body.account),
        account_display=body.account,
        password_hash=passwords.hash(body.password),
        role=role,
        name=name,
        profile=profile or {},
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        fail(409, "account_exists")
    return user


@router.post("/auth/register", response_model=UserView, status_code=201, operation_id="register")
async def register(body: Register, request: Request, session: AsyncSession = Depends(db)):
    check_origin(request)
    return public_user(await insert_user(body, session))


@router.post("/auth/sessions", response_model=SessionView, operation_id="login")
async def login(
    body: Login, request: Request, response: Response, session: AsyncSession = Depends(db)
):
    check_origin(request)
    user = (
        await session.execute(
            select(User).where(User.account == normalize(body.account), User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not user or not check_password(user.password_hash, body.password):
        fail(401, "invalid_credentials")
    if user.role == "ban":
        fail(403, "account_banned")
    return await create_session(user, request, response)


@router.get("/auth/session", response_model=SessionView, operation_id="currentSession")
async def get_session(request: Request, response: Response, user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return {**public_user(user), "role": user.role, "csrf_token": request.state.auth["csrf"]}


@router.delete("/auth/session", status_code=204, operation_id="logout")
async def logout(request: Request, response: Response, user: User = Depends(current_user)):
    await redis.delete(f"auth:session:{request.cookies[COOKIE]}")
    response.delete_cookie(
        COOKIE, path="/", secure=COOKIE.startswith("__Host-"), httponly=True, samesite="lax"
    )


@router.get("/users/me", operation_id="getMyProfile")
async def get_profile(user: User = Depends(current_user)):
    return {**public_user(user), **user.profile, "role": user.role, "account": user.account_display}


@router.patch("/users/me", operation_id="updateMyProfile")
async def update_profile(
    body: Profile, user: User = Depends(current_user), session: AsyncSession = Depends(db)
):
    user.name = body.name
    user.profile = body.model_dump(exclude={"name"})
    await session.commit()
    return {**public_user(user), **user.profile}


@router.get("/users", operation_id="listPublicUsers")
async def list_public_users(
    query: queries.PageQuery = Depends(queries.users), session: AsyncSession = Depends(db)
):
    from .content import page_rows

    filters = [*query.filters, User.role != "ban"]
    if query.q:
        filters.append(
            or_(User.name.ilike(f"%{query.q}%"), User.profile["bio"].astext.ilike(f"%{query.q}%"))
        )
    return await page_rows(
        session,
        User,
        filters,
        query.page,
        query.page_size,
        public_user,
        order=query.order(User, {"name": User.name}),
    )


@router.get("/users/{value}", response_model=UserView, operation_id="getPublicUser")
async def get_public_user(value: str, session: AsyncSession = Depends(db)):
    return public_user(await active(session, User, value))


@router.get("/admin/users", operation_id="listUsers")
async def list_users(
    query: queries.PageQuery = Depends(queries.users),
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    from .content import page_rows

    filters = list(query.filters)
    if query.q:
        filters.append(
            or_(
                User.account.ilike(f"%{query.q}%"),
                User.name.ilike(f"%{query.q}%"),
                User.profile["bio"].astext.ilike(f"%{query.q}%"),
            )
        )
    return await page_rows(
        session,
        User,
        filters,
        query.page,
        query.page_size,
        lambda row: {**public_user(row), "account": row.account_display, "role": row.role},
        True,
        order=query.order(User, {"name": User.name}),
    )


@router.post("/admin/users", status_code=201, operation_id="createUser")
async def create_user(
    body: AdminUser, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    row = await insert_user(
        body, session, body.role, body.name, {"avatar_url": body.avatar_url, "bio": body.bio}
    )
    return {**public_user(row), "role": row.role}


@router.get("/admin/users/{value}", operation_id="getUser")
async def get_user(value: str, user: User = Depends(admin), session: AsyncSession = Depends(db)):
    row = await active(session, User, value)
    return {**public_user(row), "account": row.account_display, "role": row.role, **row.profile}


@router.patch("/admin/users/{value}", operation_id="updateUser")
async def update_user(
    value: str,
    body: AdminUserUpdate,
    user: User = Depends(admin),
    session: AsyncSession = Depends(db),
):
    row = await active(session, User, value, True)
    if row.id == user.id and body.role and body.role != "admin":
        fail(409, "cannot_demote_self")
    for key, val in body.model_dump(exclude_none=True).items():
        if key in {"name", "role"}:
            setattr(row, key, val)
        else:
            row.profile = {**row.profile, key: val}
    await session.commit()
    if row.role == "ban":
        await revoke_user(row.id)
    return {**public_user(row), "role": row.role}


@router.delete("/admin/users/{value}", status_code=204, operation_id="deleteUser")
async def delete_user(value: str, user: User = Depends(admin), session: AsyncSession = Depends(db)):
    row = await active(session, User, value, True)
    if row.id == user.id:
        fail(409, "cannot_delete_self")
    row.deleted_at, row.profile, row.name = now(), {}, "已刪除使用者"
    interviews = (
        await session.scalars(
            select(Interview).where(Interview.owner_id == row.id).with_for_update()
        )
    ).all()
    for interview in interviews:
        interview.deleted_at, interview.pending_event_id = now(), None
        interview.version += 1
    session.add(
        Outbox(
            aggregate_id=row.id, version=1, kind="user_cleanup", payload={"user_id": str(row.id)}
        )
    )
    await session.commit()
    await revoke_user(row.id)

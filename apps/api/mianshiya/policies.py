import asyncio
import ipaddress
import json
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, Request
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Bank, Policy, Session, User, db
from .schemas import PolicyInput
from .security import Bloom, admin, fail, public_user, redis

router = APIRouter(prefix="/api/v1", tags=["policies"])
DEFAULTS = {
    "ip": {"blacklist": [], "whitelist": []},
    "rate": {"requests": 120, "window_seconds": 60, "hot_requests": 60},
    "crawl": {"warning_reads": 30, "max_reads": 60, "window_seconds": 60, "cooldown_seconds": 60},
    "breaker": {"failure_threshold": 3, "cooldown_seconds": 30},
    "cache": {"hot_threshold": 10, "window_seconds": 60, "ttl_seconds": 5, "local_ttl_seconds": 1},
}
last_good = {k: dict(v) for k, v in DEFAULTS.items()}
ip_filter = Bloom([])
ip_allow = frozenset()
loaded_at = 0.0
refresh_lock = asyncio.Lock()
local_limits = OrderedDict()
local_banks = OrderedDict()
cache_stats = {"redis_hits": 0, "local_hits": 0, "db_reads": 0, "misses": 0}


def canonical_ip(address):
    if not isinstance(address, str):
        raise ValueError("IP must be a string")
    parsed = ipaddress.ip_address(address)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    return str(parsed)


def validate(name, value):
    if name not in DEFAULTS or set(value) != set(DEFAULTS[name]):
        fail(422, "invalid_policy_fields")
    if name == "ip":
        for key in ("blacklist", "whitelist"):
            if not isinstance(value[key], list) or len(value[key]) > 10000:
                fail(422, "invalid_ip_list")
            normalized = set()
            for address in value[key]:
                try:
                    normalized.add(canonical_ip(address))
                except (ValueError, TypeError):
                    fail(422, "invalid_ip")
            value[key] = sorted(normalized)
    elif any(
        isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 10000 for v in value.values()
    ):
        fail(422, "invalid_policy_value")
    if name == "cache" and (
        value["ttl_seconds"] > 5 or value["local_ttl_seconds"] > value["ttl_seconds"]
    ):
        fail(422, "cache_freshness_limit")
    if name == "crawl" and value["warning_reads"] > value["max_reads"]:
        fail(422, "invalid_crawl_thresholds")


async def policies():
    global loaded_at, last_good, ip_filter, ip_allow
    if time.monotonic() - loaded_at < 1:
        return last_good
    async with refresh_lock:
        if time.monotonic() - loaded_at < 1:
            return last_good
        try:
            async with Session() as session:
                rows = (await session.scalars(select(Policy))).all()
            candidate = {
                **{k: dict(v) for k, v in DEFAULTS.items()},
                **{row.name: row.value for row in rows},
            }
            for name in DEFAULTS:
                validate(name, candidate[name])
            blocked = Bloom(candidate["ip"]["blacklist"])
            allowed = frozenset(candidate["ip"]["whitelist"])
            last_good, ip_filter, ip_allow = candidate, blocked, allowed
            loaded_at = time.monotonic()
            from .ai import ai_circuit
            from .search import es_circuit

            for circuit in (ai_circuit, es_circuit):
                circuit.threshold = last_good["breaker"]["failure_threshold"]
                circuit.cooldown = last_good["breaker"]["cooldown_seconds"]
        except Exception:
            # Explicit last-known-good policy when persistence is temporarily unavailable.
            loaded_at = time.monotonic()
    return last_good


async def limit(key, maximum, window):
    script = "local n=redis.call('INCR',KEYS[1]);if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end;return {n,redis.call('TTL',KEYS[1])}"
    try:
        count, ttl = await redis.eval(script, 1, key, window)
        return count > maximum, max(1, ttl)
    except RedisError:
        stamp = time.monotonic()
        count, end = local_limits.get(key, (0, stamp + window))
        if stamp >= end:
            count, end = 0, stamp + window
        local_limits[key] = (count + 1, end)
        local_limits.move_to_end(key)
        while len(local_limits) > 2048:
            local_limits.popitem(last=False)
        return count + 1 > maximum, max(1, int(end - stamp))


async def guard_request(request: Request):
    rules = await policies()
    address = request.client.host if request.client else "unknown"
    try:
        address = canonical_ip(address)
    except ValueError:
        address = "unknown"
    if ip_filter.contains(address) and address not in ip_allow:
        fail(403, "ip_blocked")
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    rate = rules["rate"]
    denied, ttl = await limit(f"rate:{address}:{path}", rate["requests"], rate["window_seconds"])
    if denied:
        from fastapi import HTTPException

        raise HTTPException(429, "rate_limited", headers={"Retry-After": str(ttl)})
    if path in {"/api/v1/questions/{value}", "/api/v1/banks/{value}"}:
        target = request.path_params.get("value", "")
        denied, ttl = await limit(
            f"hot-limit:{address}:{path}:{target}", rate["hot_requests"], rate["window_seconds"]
        )
        if denied:
            from fastapi import HTTPException

            raise HTTPException(429, "hot_rate_limited", headers={"Retry-After": str(ttl)})
    if path == "/api/v1/questions/{value}":
        crawl = rules["crawl"]
        cooldown_key = f"crawl:cooldown:{address}"
        try:
            cooldown = await redis.ttl(cooldown_key)
        except RedisError:
            cooldown = -1
        denied, ttl = await limit(f"crawl:{address}", crawl["max_reads"], crawl["window_seconds"])
        if cooldown > 0 or denied:
            try:
                if cooldown <= 0:
                    await redis.set(cooldown_key, "1", ex=crawl["cooldown_seconds"])
            except RedisError:
                pass
            from fastapi import HTTPException

            raise HTTPException(
                429,
                "crawl_cooldown",
                headers={"Retry-After": str(max(cooldown, crawl["cooldown_seconds"]))},
            )
        try:
            count = int(await redis.get(f"crawl:{address}") or 0)
            request.state.crawl_warning = count > crawl["warning_reads"]
        except RedisError:
            pass


async def cached_bank(value, session):
    from .content import bank_view
    from .security import active

    rules = (await policies())["cache"]
    from .security import identity

    canonical = (
        await session.execute(
            select(Bank.version, User)
            .join(User, User.id == Bank.creator_id)
            .where(Bank.id == identity(value), Bank.deleted_at.is_(None))
        )
    ).one_or_none()
    if canonical is None:
        fail(404, "not_found")
    version, author = canonical
    author_view = public_user(author)
    stamp = time.monotonic()
    cached = local_banks.get(value)
    if cached and cached[0] > stamp and cached[1]["version"] == version:
        cache_stats["local_hits"] += 1
        return {**cached[1], "author": author_view}
    key = f"cache:bank:{value}"
    try:
        payload = await redis.get(key)
        if payload and json.loads(payload)["version"] == version:
            result = json.loads(payload)
            cache_stats["redis_hits"] += 1
            local_banks[value] = (stamp + rules["local_ttl_seconds"], result)
            local_banks.move_to_end(value)
            while len(local_banks) > 256:
                local_banks.popitem(last=False)
            return {**result, "author": author_view}
    except RedisError:
        pass
    cache_stats["misses"] += 1
    row = await active(session, Bank, value)
    result = bank_view(row)
    cache_stats["db_reads"] += 1
    try:
        hot, _ = await limit(
            f"hot-detect:bank:{value}", rules["hot_threshold"], rules["window_seconds"]
        )
        if hot:
            await redis.set(key, json.dumps(result), ex=rules["ttl_seconds"])
    except RedisError:
        pass
    return {**result, "author": author_view}


@router.get("/admin/policies/{name}", operation_id="getPolicy")
async def get_policy(name: str, user: User = Depends(admin), session: AsyncSession = Depends(db)):
    if name not in DEFAULTS:
        fail(404, "not_found")
    row = await session.scalar(select(Policy).where(Policy.name == name))
    return {
        "name": name,
        "version": row.version if row else 0,
        "value": row.value if row else DEFAULTS[name],
    }


@router.patch("/admin/policies/{name}", operation_id="updatePolicy")
async def update_policy(
    name: str, body: PolicyInput, user: User = Depends(admin), session: AsyncSession = Depends(db)
):
    validate(name, body.value)
    row = await session.scalar(select(Policy).where(Policy.name == name).with_for_update())
    if (row.version if row else 0) != body.version:
        fail(409, "version_conflict")
    if row:
        row.version, row.value, row.updated_by = row.version + 1, body.value, user.id
    else:
        row = Policy(name=name, version=1, value=body.value, updated_by=user.id)
        session.add(row)
    await session.commit()
    global loaded_at
    loaded_at = 0
    return {"name": name, "version": row.version, "value": row.value}


@router.get("/admin/cache/stats", operation_id="getCacheStats")
async def stats(user: User = Depends(admin)):
    return {
        **cache_stats,
        "local_entries": len(local_banks),
        "local_limit_entries": len(local_limits),
    }

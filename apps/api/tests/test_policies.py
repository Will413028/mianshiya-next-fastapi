import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mianshiya import ai, policies
from mianshiya.db import Policy, Session
from mianshiya.main import app
from mianshiya.security import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from test_product import account, client

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_real_redis_limiter_has_one_atomic_shared_budget():
    results = await asyncio.gather(*[policies.limit("atomic-budget", 20, 60) for _ in range(100)])
    assert sum(not denied for denied, _ in results) == 20
    assert sum(denied for denied, _ in results) == 80
    assert int(await redis.get("atomic-budget")) == 100
    assert all(1 <= ttl <= 60 for _, ttl in results)


async def test_local_limiter_fallback_is_bounded_and_expires(monkeypatch):
    stamp = [1000.0]
    monkeypatch.setattr(policies, "time", SimpleNamespace(monotonic=lambda: stamp[0]))

    async def unavailable(*args, **kwargs):
        raise RedisConnectionError("isolated outage fixture")

    monkeypatch.setattr(redis, "eval", unavailable)
    assert (await policies.limit("fallback", 1, 2))[0] is False
    assert (await policies.limit("fallback", 1, 2))[0] is True
    stamp[0] += 3
    assert (await policies.limit("fallback", 1, 2))[0] is False
    for index in range(2100):
        await policies.limit(f"bounded-{index}", 1, 60)
    assert len(policies.local_limits) == 2048


async def test_policy_database_outage_keeps_last_good_snapshot(monkeypatch):
    expected = await policies.policies()

    class UnavailableSession:
        async def __aenter__(self):
            raise RuntimeError("isolated policy persistence outage")

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(policies, "Session", UnavailableSession)
    policies.loaded_at = 0
    assert await policies.policies() == expected


async def test_breaker_allows_only_one_half_open_probe(monkeypatch):
    stamp = [1000.0]
    monkeypatch.setattr(ai, "time", SimpleNamespace(monotonic=lambda: stamp[0]))
    circuit = ai.Circuit(threshold=3, cooldown=30)
    for _ in range(3):
        circuit.failure()
    with pytest.raises(ai.ProviderUnavailable):
        circuit.enter()
    stamp[0] += 31
    circuit.enter()
    with pytest.raises(ai.ProviderUnavailable):
        circuit.enter()
    circuit.success()
    circuit.enter()
    assert circuit.failures == 0 and circuit.open_until == 0 and circuit.probe is False


async def test_ipv6_rules_are_canonical_and_numeric_addresses_rejected():
    async with client() as admin:
        await account(admin, role="admin")
        response = await admin.patch(
            "/api/v1/admin/policies/ip",
            json={"version": 0, "value": {"blacklist": ["0:0:0:0:0:0:0:1"], "whitelist": []}},
        )
        assert response.status_code == 200 and response.json()["value"]["blacklist"] == ["::1"]
        policies.loaded_at = 0
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("::1", 1234)),
            base_url="http://localhost:3000",
        ) as ipv6:
            assert (
                await ipv6.get("/api/v1/health", headers={"X-Forwarded-For": "203.0.113.99"})
            ).status_code == 403
        assert (
            await admin.patch(
                "/api/v1/admin/policies/ip",
                json={"version": 1, "value": {"blacklist": [123], "whitelist": []}},
            )
        ).status_code == 422
        assert policies.canonical_ip("::ffff:127.0.0.1") == "127.0.0.1"


async def test_invalid_persisted_policy_does_not_publish_partial_snapshot():
    async with client() as admin:
        owner = await account(admin, role="admin")
    expected = await policies.policies()
    expected_filter = policies.ip_filter
    async with Session() as session:
        session.add(
            Policy(
                name="rate",
                value={"requests": 0, "window_seconds": 60, "hot_requests": 60},
                updated_by=int(owner["id"]),
            )
        )
        await session.commit()
    policies.loaded_at = 0
    assert await policies.policies() is expected
    assert policies.ip_filter is expected_filter

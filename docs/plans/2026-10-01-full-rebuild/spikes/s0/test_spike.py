import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from elasticsearch import Elasticsearch
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

WEB = os.environ["S0_WEB_ORIGIN"]
API = os.environ["S0_API_ORIGIN"]


def login(client, actor="alice"):
    response = client.post("/api/spike/login", json={"actor": actor}, headers={"Origin": WEB})
    assert response.status_code == 200
    return response


def test_ssr_cookie_forwarding():
    with httpx.Client(base_url=WEB) as client:
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert 'data-identity="alice"' in response.text
        assert "9007199254740993" in response.text


def test_identity_and_anonymous_cache_isolation():
    with httpx.Client(base_url=WEB) as a, httpx.Client(base_url=WEB) as b, httpx.Client(base_url=WEB) as anonymous:
        login(a, "alice"); login(b, "bob")
        for _ in range(3):
            assert 'data-identity="alice"' in a.get("/").text
            assert 'data-identity="bob"' in b.get("/").text
            assert 'data-identity="anonymous"' in anonymous.get("/").text


def test_proxy_cookie_attributes_revocation_and_csrf():
    with httpx.Client(base_url=WEB) as client:
        assert client.get("/api/spike/session").status_code == 401
        response = login(client)
        attrs = response.headers["set-cookie"].lower().split(";", 1)[1]
        assert "httponly" in attrs and "samesite=lax" in attrs and "path=/" in attrs
        assert "domain=" not in attrs
        assert response.json()["id"] == "9007199254740993"
        cookie = client.cookies.get("mianshiya_spike_session")
        assert client.post("/api/spike/mutation").status_code == 403
        assert client.post("/api/spike/mutation", headers={"Origin": "https://invalid.example"}).status_code == 403
        assert client.post("/api/spike/mutation", headers={"Origin": WEB}).status_code == 200
        assert client.post("/api/spike/logout", headers={"Origin": WEB}).status_code == 200
        assert client.get("/api/spike/session").status_code == 401
        # Keep the revoked cookie only in process memory; never include its value in reports.
        revoked = client.get("/api/spike/session", headers={"Cookie": "mianshiya_spike_session=" + cookie})
        assert revoked.status_code == 401
        assert 'data-identity="anonymous"' in client.get("/").text


def test_openapi_id_is_string_and_unknown_fields_rejected():
    schema = httpx.get(API + "/openapi.json").json()
    assert schema["components"]["schemas"]["Actor"]["properties"]["id"]["type"] == "string"
    response = httpx.post(API + "/api/spike/login", json={"actor": "alice", "role": "admin"}, headers={"Origin": WEB})
    assert response.status_code == 422


def test_postgres_identity_unique_rollback_and_time():
    engine = create_engine(os.environ["S0_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE contract_fixture (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, account TEXT NOT NULL UNIQUE, at TIMESTAMPTZ NOT NULL, tags JSONB NOT NULL)"))
        connection.execute(text("INSERT INTO contract_fixture(account,at,tags) VALUES ('a','2026-12-31T16:00:00Z','[\"python\"]')"))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO contract_fixture(account,at,tags) VALUES ('b',now(),'[]')"))
            connection.execute(text("INSERT INTO contract_fixture(account,at,tags) VALUES ('a',now(),'[]')"))
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT account, at, tags FROM contract_fixture ORDER BY id")).all()
        assert len(rows) == 1 and rows[0].account == "a"
        assert rows[0].at.astimezone(ZoneInfo("Asia/Taipei")).year == 2027
        assert rows[0].tags == ["python"]
    engine.dispose()


def test_bitmap_year_leapday_and_repeat():
    r = Redis.from_url(os.environ["S0_REDIS_URL"])
    for instant, date, offset in [
        ("2026-12-31T15:59:59+00:00", "2026-12-31", 364),
        ("2026-12-31T16:00:00+00:00", "2027-01-01", 0),
        ("2028-02-28T16:00:00+00:00", "2028-02-29", 59),
    ]:
        local = datetime.fromisoformat(instant).astimezone(ZoneInfo("Asia/Taipei"))
        assert local.date().isoformat() == date
        day_index = local.timetuple().tm_yday - 1
        assert day_index == offset
        key = f"s0:activity:alice:{local.year}"
        r.setbit(key, day_index, 1)
        r.setbit(key, day_index, 1)
        assert r.getbit(key, offset) == 1
        assert r.bitcount(key) == 1
        assert r.ttl(key) == -1
    r.close()


def test_chinese_search_filters_delete_and_tokens():
    es = Elasticsearch(os.environ["S0_ES_URL"])
    index = "mianshiya-s0-chinese"
    es.indices.create(index=index, mappings={"properties": {
        "title": {"type": "text", "analyzer": "cjk"},
        "content": {"type": "text", "analyzer": "cjk"},
        "answer": {"type": "text", "analyzer": "cjk"},
        "tags": {"type": "keyword"}, "bank_ids": {"type": "keyword"},
    }})
    fixtures = [
        ("1", "資料庫交易如何避免重複帳號", ["python", "database"], ["1"]),
        ("2", "資料庫交易與索引設計", ["database"], ["2"]),
        ("3", "数据库事务与索引设计", ["database"], ["2"]),
    ]
    for identity, title, tags, banks in fixtures:
        es.index(index=index, id=identity, document={"title": title, "content": "", "answer": "", "tags": tags, "bank_ids": banks})
    es.indices.refresh(index=index)
    tokens = [item["token"] for item in es.indices.analyze(index=index, analyzer="cjk", text="資料庫交易")["tokens"]]
    assert "資料" in tokens and "交易" in tokens
    def search(query, filters):
        return {hit["_id"] for hit in es.search(index=index, query={"bool": {
            "must": [{"multi_match": {"query": query, "fields": ["title", "content", "answer"], "operator": "and"}}],
            "filter": filters,
        }})["hits"]["hits"]}
    assert search("資料庫交易", [{"term": {"bank_ids": "1"}}]) == {"1"}
    assert search("資料庫交易", [{"term": {"tags": "python"}}, {"term": {"tags": "database"}}]) == {"1"}
    assert search("资料库", []) == set()  # No implicit simplified/traditional conversion.
    assert search("数据库事务", []) == {"3"}
    es.delete(index=index, id="1", refresh=True)
    assert search("資料庫交易", [{"term": {"bank_ids": "1"}}]) == set()
    es.close()

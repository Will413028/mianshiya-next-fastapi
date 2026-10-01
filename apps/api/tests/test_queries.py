import pytest
from mianshiya.db import Bank, Interview, Question, Session, User
from test_product import account, client, material

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_query_filters_sort_and_unknown_parameters():
    async with client() as c:
        author = await account(c, role="admin")
        bank, question = await material(c)
        second = await c.post(
            "/api/v1/questions",
            json={
                "title": "另一題",
                "content": "不同內容",
                "answer": "不同答案",
                "tags": ["python"],
            },
        )
        assert second.status_code == 201
        response = await c.get(
            "/api/v1/questions",
            params={
                "content": "並行",
                "answer": "UNIQUE",
                "tags": ["database", "python"],
                "creator_id": author["id"],
                "sort": "title",
                "order": "asc",
            },
        )
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["items"]] == [question["id"]]
        assert (
            await c.get(
                "/api/v1/questions", params={"id": question["id"], "not_id": question["id"]}
            )
        ).json()["total"] == 0
        assert (await c.get("/api/v1/banks", params={"q": "一致性", "id": bank["id"]})).json()[
            "total"
        ] == 1
        assert (await c.get("/api/v1/banks", params={"description": "不存在"})).json()["total"] == 0
        assert (
            await c.post(
                "/api/v1/bank-question-relations",
                json={"bank_id": bank["id"], "question_id": question["id"]},
            )
        ).status_code == 201
        detail = await c.get(
            "/api/v1/banks/" + bank["id"], params={"include_questions": True, "page_size": 1}
        )
        assert detail.status_code == 200
        assert detail.json()["question_page"]["total"] == 1
        assert detail.json()["question_page"]["items"][0]["id"] == question["id"]
        assert (await c.get("/api/v1/banks/" + bank["id"])).json()["question_page"] is None
        for params in (
            {"sort": "password_hash"},
            {"order": "sideways"},
            {"page": 0},
            {"page_size": 21},
            {"unexpected": "x"},
            {"id": "01"},
        ):
            assert (await c.get("/api/v1/questions", params=params)).status_code == 422


async def test_user_search_privacy_and_interview_owner_filters():
    async with client() as admin, client() as learner:
        manager = await account(admin, "private-search-account", "admin")
        person = await account(learner, "another-private-account")
        assert (
            await learner.patch("/api/v1/users/me", json={"name": "公開名稱", "bio": "公開簡介"})
        ).status_code == 200
        assert (await admin.get("/api/v1/users", params={"q": "private-search-account"})).json()[
            "total"
        ] == 0
        assert (
            await admin.get("/api/v1/admin/users", params={"q": "private-search-account"})
        ).json()["total"] == 1
        assert (
            await admin.get("/api/v1/users", params={"bio": "公開簡介", "id": person["id"]})
        ).json()["total"] == 1
        response = await learner.post(
            "/api/v1/interviews",
            json={"position": "Python engineer", "experience": "三年", "difficulty": "medium"},
        )
        assert response.status_code == 201
        filters = {
            "position": "Python",
            "experience": "三",
            "difficulty": "medium",
            "status": "NOT_STARTED",
            "owner_id": person["id"],
        }
        assert (await admin.get("/api/v1/admin/interviews", params=filters)).json()["total"] == 1
        assert (await admin.get("/api/v1/interviews", params=filters)).json()["total"] == 0
        filters["owner_id"] = manager["id"]
        assert (await learner.get("/api/v1/interviews", params=filters)).json()["total"] == 0


async def test_deleted_author_projection_keeps_content_and_removes_private_profile():
    async with client() as admin, client() as author:
        await account(admin, "surviving-manager", "admin")
        owner = await account(author, "content-owner", "admin")
        assert (
            await author.patch(
                "/api/v1/users/me",
                json={"name": "原作者", "bio": "公開簡介", "phone": "private-phone"},
            )
        ).status_code == 200
        bank, question = await material(author)
        assert (await admin.get("/api/v1/questions/" + question["id"])).json()["author"][
            "name"
        ] == "原作者"
        assert (await admin.get("/api/v1/banks/" + bank["id"])).json()["author"]["name"] == "原作者"
        interview = await author.post(
            "/api/v1/interviews",
            json={"position": "Python", "experience": "初階", "difficulty": "easy"},
        )
        assert interview.status_code == 201
        assert (await admin.delete("/api/v1/admin/users/" + owner["id"])).status_code == 204
        assert (await author.get("/api/v1/auth/session")).status_code == 401
        for path in ("/questions/" + question["id"], "/banks/" + bank["id"]):
            response = await admin.get("/api/v1" + path)
            assert response.status_code == 200
            assert response.json()["creator_id"] == owner["id"]
            assert response.json()["author"] == {
                "id": owner["id"],
                "name": "已刪除使用者",
                "avatar_url": "",
                "bio": "",
            }
        assert (await admin.get("/api/v1/questions", params={"creator_id": owner["id"]})).json()[
            "items"
        ][0]["author"]["name"] == "已刪除使用者"
        assert (
            await admin.patch("/api/v1/questions/" + question["id"], json={"title": "接管後題目"})
        ).status_code == 200
        async with Session() as session:
            person = await session.get(User, int(owner["id"]))
            meeting = await session.get(Interview, int(interview.json()["id"]))
            assert person.deleted_at is not None and person.profile == {}
            assert meeting.deleted_at is not None
            assert (await session.get(Bank, int(bank["id"]))).deleted_at is None
            assert (await session.get(Question, int(question["id"]))).deleted_at is None

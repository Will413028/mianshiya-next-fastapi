import pytest
from mianshiya.db import Question, Session, User
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from test_product import account, client

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_migrated_identity_and_database_owned_contracts():
    async with client() as c:
        person = await account(c)
    async with Session() as session:
        identities = (
            await session.execute(
                text(
                    "SELECT table_name, identity_generation FROM information_schema.columns WHERE table_schema='public' AND column_name='id'"
                )
            )
        ).all()
        assert len(identities) == 8 and all(
            row.identity_generation == "ALWAYS" for row in identities
        )
    for tags in ({"unexpected": "object"}, ["good", 42]):
        async with Session() as session:
            session.add(
                Question(
                    title="型別約束",
                    content="題幹",
                    answer="題解",
                    tags=tags,
                    creator_id=int(person["id"]),
                )
            )
            with pytest.raises(IntegrityError) as failure:
                await session.commit()
            assert failure.value.orig.sqlstate == "23514"
    async with Session() as session:
        row = await session.get(User, int(person["id"]))
        row.role = "invalid-role"
        with pytest.raises(IntegrityError) as failure:
            await session.commit()
        assert failure.value.orig.sqlstate == "23514"
    async with Session() as session:
        with pytest.raises(ProgrammingError) as failure:
            await session.execute(
                text(
                    "INSERT INTO questions(id,title,content,answer,tags,creator_id,version,review_status) VALUES (1234,'explicit ID','','','[]',:owner,1,'approved')"
                ),
                {"owner": int(person["id"])},
            )
        assert failure.value.orig.sqlstate == "428C9"

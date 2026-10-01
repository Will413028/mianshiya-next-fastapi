import asyncio

from alembic import context

from mianshiya.db import Base, engine


def configure(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    async with engine.connect() as connection:
        await connection.run_sync(configure)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Use a local database for migration validation")
else:
    asyncio.run(online())

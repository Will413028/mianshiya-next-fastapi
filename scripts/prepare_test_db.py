"""Create only the isolated integration database; never truncate product data."""

import asyncio
import os

import psycopg
from sqlalchemy.engine import make_url


async def main():
    url = make_url(
        os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/mianshiya")
    )
    url = url.set(drivername="postgresql", database="postgres")
    try:
        async with await psycopg.AsyncConnection.connect(
            url.render_as_string(hide_password=False), autocommit=True, connect_timeout=5
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", ("mianshiya_test",)
                )
                if not await cursor.fetchone():
                    await cursor.execute("CREATE DATABASE mianshiya_test")
    except psycopg.Error:
        raise SystemExit(
            "Unable to create isolated test database; verify PostgreSQL readiness and permissions"
        ) from None
    print("Isolated test database ready")


if __name__ == "__main__":
    asyncio.run(main())

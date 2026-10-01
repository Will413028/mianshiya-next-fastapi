import argparse
import asyncio
import json
import secrets
from pathlib import Path

from sqlalchemy import select

from .db import Bank, Outbox, Question, Relation, Session, User
from .security import normalize, passwords


async def seed():
    async with Session() as session:
        existing = await session.scalar(select(User).where(User.account == "curriculum-author"))
        if existing:
            return
        author = User(
            account="curriculum-author",
            account_display="curriculum-author",
            password_hash=passwords.hash(secrets.token_urlsafe(32)),
            name="教材作者",
            role="user",
            profile={},
        )
        session.add(author)
        await session.flush()
        topics = [
            (
                "Python 基礎",
                "理解資料結構、函式與錯誤處理",
                [
                    (
                        "list 與 tuple 如何選擇？",
                        "比較兩種序列的可變性與典型使用場景。",
                        "list 可以原地新增、刪除或替換元素；tuple 的元素位置不能修改。需要固定結構時可用 tuple，需要持續調整集合時用 list。tuple 內的可變物件仍可修改，不能把它當深層不可變。",
                        ["Python", "資料結構"],
                    ),
                    (
                        "為什麼要用 context manager？",
                        "說明 with 如何管理資源。",
                        "context manager 定義進入與離開資源範圍的行為。即使區塊拋出錯誤，__exit__ 仍可關閉檔案或釋放鎖。資料庫 transaction 也適合用 context manager 清楚表示 commit 與 rollback 邊界。",
                        ["Python", "資源管理"],
                    ),
                ],
            ),
            (
                "資料庫與系統設計",
                "練習交易、索引與非同步一致性",
                [
                    (
                        "交易如何避免重複帳號？",
                        "兩個 API 同時註冊相同帳號時如何保證正確性？",
                        "由資料庫 UNIQUE 約束決定唯一性。應用先查詢只能改善錯誤提示，無法消除競態。兩個 transaction 同時寫入時，一個成功，另一個處理 uniqueness conflict 並 rollback，對外回傳 409。",
                        ["PostgreSQL", "交易"],
                    ),
                    (
                        "什麼是 transactional outbox？",
                        "資料寫入成功，但搜尋索引暫時無法更新時怎麼辦？",
                        "把業務資料與待發布事件放在同一筆資料庫 transaction。worker 重試發送並於成功後 ack。消費端使用 aggregate version 與冪等操作處理重播和亂序，避免刪除資料被旧事件復活。",
                        ["系統設計", "一致性"],
                    ),
                ],
            ),
            (
                "前端與 API",
                "練習 SSR、型別契約與安全邊界",
                [
                    (
                        "SSR 如何保留登入者身分？",
                        "Next.js server fetch 為什麼不會自動帶瀏覽器 cookie？",
                        "SSR 是伺服器發出的新請求，應明確把必要 cookie 傳給內部 API。個人化結果需 no-store，避免跨使用者共享。權限仍由 API 驗證，前端隱藏按鈕不是授權。",
                        ["Next.js", "安全"],
                    ),
                    (
                        "為什麼 API 的 bigint ID 使用字串？",
                        "JavaScript 如何處理超過 2^53−1 的資料庫 ID？",
                        "Number 無法精確表示所有 64-bit 整數。API 輸出十進位字串並保留字串傳遞；後端驗證範圍後轉成資料庫整數。避免 JSON parser 或 URL 操作把它轉成 Number。",
                        ["TypeScript", "API"],
                    ),
                ],
            ),
        ]
        for title, description, questions in topics:
            bank = Bank(title=title, description=description, creator_id=author.id)
            session.add(bank)
            await session.flush()
            for heading, content, answer, tags in questions:
                question = Question(
                    title=heading, content=content, answer=answer, tags=tags, creator_id=author.id
                )
                session.add(question)
                await session.flush()
                session.add(
                    Relation(bank_id=bank.id, question_id=question.id, creator_id=author.id)
                )
                session.add(
                    Outbox(aggregate_id=question.id, version=1, kind="question", payload={})
                )
        await session.commit()


async def promote(account):
    async with Session() as session:
        row = await session.scalar(
            select(User).where(User.account == normalize(account), User.deleted_at.is_(None))
        )
        if not row:
            raise RuntimeError("Register the account before promoting it")
        row.role = "admin"
        await session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed", "promote", "openapi"])
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if args.command == "openapi":
        from .main import app

        Path(args.argument or "openapi.json").write_text(
            json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
        )
    elif args.command == "seed":
        asyncio.run(seed())
    else:
        if not args.argument:
            parser.error("promote requires an account name")
        asyncio.run(promote(args.argument))

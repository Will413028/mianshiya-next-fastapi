"""Live provider contract probe; never substitute this for full product journeys."""

import asyncio
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from mianshiya.ai import GeneratedBatch, completion


async def main():
    result = {"provider": "local-openai-compatible", "model": "qwen3:0.6b", "checks": {}}
    answer = await completion(
        [
            {"role": "system", "content": "你是技術面試官，使用繁體中文，回覆簡潔。"},
            {"role": "user", "content": "請問我一個 PostgreSQL transaction 的面試問題。"},
        ]
    )
    assert answer.strip()
    result["checks"]["interview_nonempty"] = True
    text = await completion(
        [
            {
                "role": "system",
                "content": "你是教材作者。產生原創題目及詳解，使用繁體中文，嚴格回傳指定 JSON。",
            },
            {
                "role": "user",
                "content": "精確產生一題 PostgreSQL transaction 面試題，包含 title/content/answer/tags。",
            },
        ],
        GeneratedBatch.model_json_schema(),
    )
    batch = GeneratedBatch.model_validate_json(text)
    assert len(batch.questions) == 1
    result["checks"]["generation_schema_exact_count"] = True
    result["samples"] = {"interview": answer, "generation": batch.model_dump()}
    (root / "reports/ai-provider-contract.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print("Live provider contract: passed")


if __name__ == "__main__":
    asyncio.run(main())

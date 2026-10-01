---
title: 完整刷題學習重做採 PostgreSQL 與安全修正方案
project: mianshiya-next-fastapi
date: 2026-10-01
review-date: 2027-04-01
status: active
tags: [decision, postgresql, learning-rebuild]
---

# 完整刷題學習重做採 PostgreSQL 與安全修正方案

## Context

來源教學平台有刷題、AI、效能安全場景及未接前端的模板整合。本專案尚無應用或部署，先前計畫的 MySQL 僅是減少換棧變數的建議；Will 在 2026-10-01 選擇 PostgreSQL 並同意按建議繼續。

- `external`：Will 明確要求 Next.js + FastAPI、personal 的全新學習版，完整產品功能、無舊資料。
- `external`：Will 選 PostgreSQL；後續授權自主完成與隔離下載，2026-10-01 收尾授權 commit、recording、decision-log；未授權秘密、push 或付費 API。
- `inherited`：固定原 repo revision 作產品範圍證據，仍成立；Java 框架與來源缺陷不構成需相容的限制。

## Options Considered

- **基準：模組化單體＋relational DB**。新應用按業務組織，以 [FastAPI APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/) 管理邊界；按需求增加 worker 與搜尋服務，不先拆 microservices。
- **D1-A 核心完整（選用）**：刷題、帳號管理、profile、Bitmap、ES、batch/cache、安全及 AI；圖片用 URL。排除 Post、按讚收藏、上傳／COS、微信與 demo endpoints 的產品實作。
- **D1-B 全後端能力**：另做模板／外部整合，學習面更廣，代價是 UI/schema、帳號與成本增多。
- **D2-A MySQL**：減少換 DB 變數，延續原 SQL 習慣。
- **D2-B PostgreSQL（選用）**：使用 relational constraints、identity、timestamptz、JSONB；增加 PostgreSQL 經驗，需重寫 migration/queries。
- **D2-C 單 DB**：改 SQL full-text／活動表，維運最少，但失去 Redis Bitmap 與 ES 場景。
- **D3-A 修正方案（選用）**：bounded atomic batch、owner/state/concurrency 保護、可恢復索引、短暫反爬 cooldown、明確 lifecycle。
- **D3-B 可見政策偏原碼**：明確 partial-result、automatic permanent ban；對照較直接，但 UI 需部分結果/解封流程。
- **D4-A 本機 Ollama（選用）**：OpenAI-compatible API 與 Qwen3:0.6b，無外部 API 費用，代價是主機記憶體與品質限制；生成題目必須 pending-review。
- **D4-B 雲端 provider**：品質與吞吐通常較佳，但需帳號、憑證與費用授權，本次不選。
- **D6 基準：有界連線池**：SQLAlchemy QueuePool 可配置固定池加 overflow，適合突發流量，代價是尖峰新連線與 PostgreSQL 預算管理。
- **D6-A 固定 10／overflow 0（選用）**：與原 5＋5 相同最大容量，減少建連 churn；代價是尖峰排隊，不能當成 p95 已通過的證據。

## Decision

- D1=A：R01–R21 全部做；R22–R25 排除產品實作，記錄理由，不公開 demo auth bypass。
- D2=B：PostgreSQL + Redis + Elasticsearch；SQLAlchemy/Alembic、業務模組化單體＋獨立 worker、DB bigint identity/API string ID、unique account/pair、soft delete 與 SQL outbox。
- D3=A：採計畫的修正方案與 user/bank/question/interview delete lifecycle；batch atomic、Taipei 活動日期、server auth/revocation、Bitmap 年度持久保存、60 秒 cooldown、admin 手動 ban。
- D4=A：依自主完成授權採本機 Ollama／Qwen3:0.6b；生成題目待人工審核。此為 agent 執行選擇，非 Will 個別指定模型。
- D5：CJK OR／tags AND；10k 題、100 題庫、1k 使用者，20 concurrency、每輪 60 秒、冷熱各三輪；detail p95≤300ms、search≤500ms、errors=0、freshness≤5s。ASGI 量測不含 Next/network。
- D6=A：固定池 10／overflow 0；保持有界可配置預算，未放寬 D5。

## Rationale

- 相較所有模板整合，核心全做能把時間用在完整的刷題產品與重要系統場景；代價是沒有微信／Post/COS 學習內容。
- PostgreSQL 是 Will 的明確學習選擇；沒有 live data，MySQL compatibility 的 inherited 限制不成立。代價是 SQL dialect、migration 與 driver 要重新驗證。
- 修正政策不追求逐行模仿，重做時安全缺陷不需保留；atomic batch 較易證明一致性，代價是限制單批大小。cooldown 降低誤判後永久 ban 的後果，仍保留可配置的防爬分級與 admin ban。
- 保留 Redis/ES 而非單 DB，是為實作原學習場景；代價是 local infra 與派生資料恢復機制更複雜。
- 相較雲端模型，本機方案能驗完整編排而不引入帳號費用；代價是小模型輸出品質有限，編排通過不等於面試內容專業。
- 固定池相較原 5＋5 溢出池，六輪建連從 3062 減為 10；代價是等待容量固定。最新六輪仍有冷啟動超標，不把主機負載相關性當成已證明根因。

## Expected Outcome

- 完成 R01–R21 的端到端與故障驗收；原 source 額外項均有批准排除記錄。
- PostgreSQL migration 可重跑，並發註冊唯一、batch rollback、outbox catch-up、面試 owner/concurrency 有負例測試。

## Followup

- S0–S12 依唯一 roadmap 補足驗收；D5 效能未通過，freshness、批次比較、恢復及 mutation 仍待。
- 新面試 phase prompt 變更後重跑 live AI；完整瀏覽器整輪與最終獨立設計審查仍待。

## Revocation Triggers

- 若 Will 要正式上線或納入外部整合，重評範圍、資料保存、登入期限及 infra 成本。
- 若 batch 上限或中文搜尋品質無法滿足驗收，先用實驗證據修訂契約，不能繞過已批准的行為。
- 若本機模型品質或固定池排隊不能滿足需求，重評模型／容量；不以調鬆驗收門檻掩蓋失敗。

## Review Notes

尚未到 review 日期。

## Related

- 本 ADR 即本次 agent discussion 的原始決策紀錄，無外部對話文件。
- [重做計畫](../../2026-10-01-full-rebuild.md)、[來源盘點](../inventory.md)。
- 固定來源：[4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9](https://github.com/liyupi/mianshiya-next/tree/4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9)。
- [PostgreSQL numeric](https://www.postgresql.org/docs/18/datatype-numeric.html)、[datetime](https://www.postgresql.org/docs/18/datatype-datetime.html)。
- [SQLAlchemy QueuePool](https://docs.sqlalchemy.org/en/20/core/pooling.html)、[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)。
- 本次 Amendment 即 agent discussion 原始紀錄；量測為 repo `reports/benchmark-baseline.json`、`benchmark-fixed-pool.json`、`benchmark.json`，隨 checkpoint commit 保留。
- 無通用 Lessons Rule 要回流；學習 repo 不建立正式專案 wiki，執行 Followup 均連回唯一計畫。

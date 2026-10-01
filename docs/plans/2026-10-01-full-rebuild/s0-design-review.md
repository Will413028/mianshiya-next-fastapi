# S0 獨立設計審查

2026-10-01，新的唯讀 reviewer 對照 source、ADR、plan、api-contract 與 S0 fixtures。範圍：ID、schema/constraints、session/auth、async/worker、transaction、cache、index/cleanup、error model、外部呼叫順序、中文 analyzer、limiter/Bloom、fixture boundaries。

共 1 finding：改 0、記 1、提 0、駁回 0。產品實作尚未開始；本審查不宣稱已審查 S1–S12 程式。

- F-S0-01：面試 history 沿用 aggregate 儲存但未重評。已記入機制盤點與契約：學習版按一場面試讀取、CAS serialization，因此保留 bounded JSONB；最多 100 輪、1 MiB（64 KiB 預留結束總結），達上限拒絕新增 chat；跨訊息 analytics／無界歷史／上限不足時重評 messages 子表。處置來源：[PostgreSQL JSON](https://www.postgresql.org/docs/18/datatype-json.html)，2026-10-01 核對。
- 指令檔核對：AGENTS 的資料棧改為 PostgreSQL；產品啟動命令尚無，spike 驗收入口於真實通過後補上。

Reviewer 認為其餘機制有明確的新約束或重評理由；D4、rebuild、pool/freshness 等已有處理時點，沒有新增僅記待決而無觸發條件的 finding。

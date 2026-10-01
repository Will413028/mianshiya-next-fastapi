# 產品設計審查

獨立唯讀 reviewer：product_design_review。範圍：ID、SQL/Alembic、auth/session、batch、outbox、ES/rebuild、Bitmap、cache、policy/Bloom、breaker、AI jobs/interviews、Next.js proxy/generated schemas。

| ID | 發現 | 處置 | 證據／驗收 |
|---|---|---|---|
| DR01 | 串行 worker 讓 AI 阻塞 outbox | 改：TaskGroup 管理獨立 outbox/generation loop，各自 Session | search.worker；故障／慢 AI 時 index freshness 測試待跑 |
| DR02 | 每個 request 重建 Bloom | 改：policy snapshot 刷新時建立 immutable filter | policies.policies／guard_request；Bloom false-positive 回歸已建，待完整跑 |
| DR03 | bank-version／policy-epoch 沒有 reader | 改：移除 marker 與 policy outbox；採 canonical SQL version／一秒 policy refresh | exact marker consumer 搜尋與多 instance policy 測試待跑 |
| DR04 | 重建 SHARE lock 成本未盤點 | 記：維護式重建，以 bulk 500 寫入；全流程 120 秒 deadline、鎖取得 5 秒上限 | 10,000 題實測停頓待跑；如超出 120 秒或需要持續寫入，改 snapshot+durable catch-up |

改 3／記 1／提 0／駁回 0。上表是累積 ledger，修正不得回歸。尚未以 reviewer 回報代替實測；所有待跑項仍擋完成。

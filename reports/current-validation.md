# 2026-10-01 session checkpoint

本檔是最新狀態；各舊報告保留歷史，不可合併部分成功宣稱全產品完成。

- `make check` 最新 exit0：Ruff、format、fixture-lock 2 units、盤點 coverage、OpenAPI/TS byte equality、typecheck、Prettier。
- 真 PostgreSQL18／Redis／ES 全套 API：26 passed，44.59s，`api-full-native.xml`。
- production build 通過；CI actionlint 通過，無 remote，未執行 GitHub CI。
- `multi-instance.json`：兩真 API processes 六項通過，包括共享 rate budget、ban/revoke、IP更新／重啟、forwarded header spoof。
- `live-ai.json`：真 worker 精確1/20題 pending-review、面試 start/chat/end/replay，165.389s。此後 phase prompts 已改，需重跑；不宣稱模型專業品質。
- 最新 browser：4 passed／1 failed；管理 CRUD／batch／Markdown 成功。Home→BankQuestion 的等待競態已修測試，修後尚未整輪重跑；桌機 pagination CSS 修後待重擷取。
- `benchmark.json`：10k題／100題庫／1k使用者，20 concurrency×60s，冷熱各3輪，errors=0，但 passed=false。cold2 detail512.30/search506.20ms；cold3 detail362.46ms。固定10池、overflow0，整輪10條新連線；不可 cherry-pick 熱輪宣稱達標。
- `benchmark-baseline.json`／`benchmark-fixed-pool.json` 保留失敗比較；ASGI 不含 Next/network。
- 所有 S0–S12 保持未勾選；completion ledger 未將未驗收項升為 verified。

## 下次入口

讀唯一 roadmap `docs/plans/2026-10-01-full-rebuild.md` 與附件 `session-handoff.md`。acceptance.py 尚保留 pending gate，不能當已完成。

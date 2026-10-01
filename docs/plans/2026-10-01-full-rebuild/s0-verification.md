# S0 驗證

狀態：程式與契約草案完成，驗收未通過；不宣稱 S0 完成。

## 可重跑入口

在 repo 根目錄使用已授權且已安裝的隔離依賴：

```sh
uv run --frozen --project docs/plans/2026-10-01-full-rebuild/spikes/s0 python docs/plans/2026-10-01-full-rebuild/spikes/s0/run.py
uv run --frozen --project docs/plans/2026-10-01-full-rebuild/spikes/s0 python docs/plans/2026-10-01-full-rebuild/spikes/s0/run.py --skip-es
python3 docs/plans/2026-10-01-full-rebuild/check_plan.py
```

runner 使用本機 cached PostgreSQL 18、Redis 8、Elasticsearch 9.5.4 image，`--pull=never`；隨機 loopback port、獨立 container 名與合成資料。最後只清理自身建立的 process/container。Python 與 Node 依賴分別由 `uv.lock` 與 `pnpm-lock.yaml` 固定。若 cache 缺少依賴，需另取得下載授權。

## 已驗證與未驗證

- PostgreSQL readiness 已通過；Next.js 16.3.8 production build 已通過。
- 原 20 秒 PostgreSQL readiness 在共享主機不夠；獨立診斷確認可連線，改為 180 秒有限等待。
- Elasticsearch 原 150 秒、300 秒及最後 600 秒等待均逾時。獨立診斷曾取得 HTTP 200；不因此把完整搜尋 fixture 記為通過。最後一輪容器 running、OOMKilled=false，結構化 ERROR/FATAL 計數 0（見 `spikes/s0/es-diagnostics.json`）；這些診斷無法證明逾時根因。
- ES 同時啟動期間，另跑 4 個拓樸測試：4 failed、3 deselected（見 `spikes/s0/topology-tests.txt`）。`--tb=no` 未保存錯誤細節，不能把它們直接歸因於 ES。
- 隔離 `--skip-es` 重跑在 PostgreSQL 180 秒 readiness 失敗，未到行為測試。因此目前不是只有 ES 未驗收；須先重現 PostgreSQL 啟動問題，再查 auth/SSR 失敗原因。
- 7 個完整行為測試與移除 SSR cookie 的 mutation 未通過／未執行。完整 HTTPS/browser CSRF、產品 migration、outbox、負載與故障驗收分別屬後續階段，這個 fixture 不代替它們。
- 文件 coverage gate 通過：71 endpoints、15 pages、5 tables、25 requirements、10 defects、13 steps。
- second-brain `lint-rules.py`、`check-links.py` 通過；24 個來源／文件／設定檔的 whitespace 與 Python AST 檢查通過。

## 契約與設計

見 [API/data 契約](api-contract.md)、[獨立設計審查](s0-design-review.md)。D1–D3 已批准；D4 與 D5 仍依主計畫擋住各自受影響階段。效能候選 fixture 與門檻在 D5；兩個合成使用者的 proxy timing 只診斷拓樸，不能宣稱產品效能。

產品尚未建立；未初始化 Git、commit 或 push。

## 接手

先讀主計畫 S0a/S0b 與本報告。所有下載仍沿用本 session 授權；換 session 若需下載，重新確認。先檢查共享 Docker 的 CPU/memory/disk 狀態，不停止其他專案容器；重現 isolated PostgreSQL readiness 並保存 metadata/log error 類型。排除 infra 原因後跑 `--skip-es`，再完整 runner。只有 6 cases + mutation 與 ES 搜尋全部通過才完成 S0；不開始 S1、不把 D5 候選當已批准。

# 面試刷題平台：Next.js + FastAPI 學習重做

從零實作 [liyupi/mianshiya-next](https://github.com/liyupi/mianshiya-next) 的產品功能，使用 Next.js、FastAPI、PostgreSQL、Redis 與 Elasticsearch；沒有舊資料搬移或 Java API 相容要求。

產品程式已建立，完整驗收仍在進行；目前狀態與逐項證據以重做計畫及其附件為準。原專案參考版本固定為 `4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9`。

- [重做計畫與進度](docs/plans/2026-10-01-full-rebuild.md)
- [功能、機制與缺陷盤點](docs/plans/2026-10-01-full-rebuild/inventory.md)
- [逐一 API、頁面與資料表清單](docs/plans/2026-10-01-full-rebuild/source-inventory.json)
- [S0 契約草案](docs/plans/2026-10-01-full-rebuild/api-contract.md)
- [S0 實測結果與重跑入口](docs/plans/2026-10-01-full-rebuild/s0-verification.md)（驗收未通過）

範例題目、文字、圖片與 AI prompts 自行製作，不直接搬入來源內容。

## 本機啟動

需要 Python 3.13、uv、Node.js、pnpm、Docker Compose。套件版本由 lockfiles 固定。以下指令在 repo 根目錄執行：

```sh
make install
make infra
make migrate
make seed
```

等待 PostgreSQL TCP、Redis 與 Elasticsearch 可回應後，再執行 migration。Compose 使用持久 volume；重啟服務不清空資料。trust 資料庫與未啟用安全模組的搜尋服務只綁 loopback，供本機學習使用。

另開三個 terminal，分別執行 `make api`、`make worker`、`make web`。前端入口為 `http://localhost:33017`，API 文件為 `http://127.0.0.1:18000/docs`。瀏覽器透過 Next.js 同源 proxy，SSR 明確轉送 cookie 並使用 `no-store`。worker 的 outbox 與 AI 排程使用獨立 coroutine／DB session。

先在前端註冊，再於 `apps/api` 執行 `uv run --frozen python -m mianshiya.cli promote YOUR_REGISTERED_ACCOUNT` 成為管理員。seed 建立三個題庫、六道原創題目；教材作者沒有預設登入密碼。

## 本機 AI

預設 provider 是 Ollama 的 OpenAI-compatible endpoint `http://127.0.0.1:11439/v1`，模型 `qwen3:0.6b`，使用 `reasoning_effort: none`。只接受完整非空答案；出題另驗 JSON schema 與精確數量，成功後仍待審核。

將官方 Ollama standalone runtime 安裝到 `.tools/ollama/`，binary 路徑為 `.tools/ollama/ollama`。執行 `python3 scripts/serve_ai.py`，再另開 terminal：

```sh
curl --fail http://127.0.0.1:11439/api/pull -H 'Content-Type: application/json' -d '{"model":"qwen3:0.6b","stream":false}'
```

啟動 API／worker 前可配置 `AI_BASE_URL`、`AI_MODEL`、`AI_REASONING_EFFORT`、`AI_API_KEY`。key 直接交給 provider，不輸出。小模型的教材品質需要人工審核。

## 檢查與驗收

```sh
make generate       # FastAPI OpenAPI → TypeScript
make check          # 計畫覆蓋、契約漂移、前端型別
make test-db        # 建立獨立 mianshiya_test
make integration    # 真 PostgreSQL／Redis／Elasticsearch
make e2e            # 已啟動的 Next.js／API，瀏覽器流程
make acceptance STEP=S2
```

Integration 僅能使用 `mianshiya_test` 與 Redis DB 15，會重設這兩個隔離 fixture。不要同時執行 integration 與 benchmark，兩者使用相同測試資料庫。E2E 使用產品 DB 建立隨機測試帳號，不刪除既有教材。首次使用 Playwright 需在 `apps/web` 執行 `pnpm exec playwright install chromium`。

普通 `make check` 不代表全部功能已驗收。效能、故障、live AI 與完整功能 ledger 都必須另通過；報告寫在 `reports/`。

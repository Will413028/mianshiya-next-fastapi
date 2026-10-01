# 專案指令

本專案是 Next.js + FastAPI 的面試刷題平台學習重做，資料層為 PostgreSQL + Redis + Elasticsearch，從零建立，沒有舊部署、舊資料或舊 API 相容要求。

- 開工先讀 `docs/plans/2026-10-01-full-rebuild.md`，核對進度、被擋於與停止條件；未決項不視為已批准。
- 原專案是產品行為的參考來源；Java 框架、缺陷與模板殘留不直接沿用。範圍與差異見計畫附件。
- 前後端 API 型別以 FastAPI OpenAPI 生成；不得在前端另寫鏡像 DTO 或權限 enum。
- 業務授權與資料隔離由 FastAPI 驗證；前端導覽限制只供使用者體驗。
- 不複製原專案的憑證設定、seed data、題目文字、圖片或 AI prompts。
- repo 根目錄的入口：`make generate` 生成 OpenAPI/TypeScript、`make check` 驗文件與型別、`make integration` 驗隔離 PostgreSQL/Redis、`make e2e` 驗瀏覽器流程；`make migrate`／`make seed`／`make api`／`make worker`／`make web` 管理本機程式。
- Integration 只准使用 `mianshiya_test` 與獨立 Redis DB 15；conftest 的資料庫 guard 不得移除。不得對產品 DB 執行 truncate/reset。
- worker 的 outbox 與 AI 工作排程互相隔離；每個 coroutine 使用自己的 SQLAlchemy Session。搜尋重建是有 deadline 的維護操作，不能聲稱零停頓。

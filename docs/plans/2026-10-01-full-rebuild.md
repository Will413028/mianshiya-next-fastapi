# Next.js + FastAPI 完整學習重做

**Goal：** 從零建立可在本機跑的面試刷題平台，完整涵蓋已確認範圍，提供可重跑的功能、故障與負載驗收。以產品能力對齊來源，不相容 Java endpoint 名稱，也不搬資料。

**上層：** 暫代主清單；此文件是唯一 roadmap 與實作進度來源。

**附件：** [功能與缺陷盘點](2026-10-01-full-rebuild/inventory.md)、[逐項來源清單](2026-10-01-full-rebuild/source-inventory.json)、[文件檢查](2026-10-01-full-rebuild/check_plan.py)。

## 全域約束與完成定義

- 已確認：Next.js + FastAPI、personal 身分、從零學習版、完整原專案功能、沒有舊資料。來源是 `liyupi/mianshiya-next` commit `4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9`，不是線上 mianshiya.com 的未知功能。
- 原 controller/template 的額外功能不得靜默排除，見 D1；原缺陷的修正與可見政策差異見 D3。只看 README 不足以定義完整。
- Will 的持續目標已授權完成全部功能、不再中途要求權限，覆蓋必要本機依賴、可逆實作與合理預設；此明確指示取代逐階段停止。持續驗證各階段，未通過不打勾；不默認開通付費服務或發布到遠端。
- 已確認 PostgreSQL + Redis + Elasticsearch。monorepo：`apps/web`、`apps/api`、`packages/api-client`、`infra`。FastAPI 採業務模組化單體，worker 共用 domain code 但独立程序；產品程式已建立，逐項驗收仍在執行。
- 每階段交付一條完整使用者流程，先薄端到端再擴充；先正確性測試再做優化比較。測試需要能辨別忽略 filter、越權、部分成功、session 撤銷等錯誤。
- 不讀取來源 config/credentials/seed，不複製原程式、題目、資產與 prompt。外部 provider 與付費部署不由 agent 默認開通。
- 完成定義：R01–R25 每項有實作驗收或已批准排除去向；每個 source endpoint/page/table 都有終態；B01–B10 每項有回歸或接受理由；`make check`/`make integration`/`make e2e` 全通過；必要 live 外部介面實測；沒有未決功能阻礙；負載與故障報告可重跑；独立設計審查已處置；README 的安裝／啟動指令在乾淨環境跑過。
- 未確認／未跑不能打勾。Fake AI 可驗證編排，不能宣稱 AI 功能完成；效能比較要列 fixture、硬體、冷熱快取與測量次數。

## 前提（2026-10-01 核對）

- 會改到或取代的既有部署是否在線：**無既有部署**。Will 已確認全新學習版，沒有資料搬移／相容性窗口；本機實作回滾是分支 revert，未建 Git 前用 reviewable patch。
- 範圍來源：Will 本 session 與固定 revision 原始碼（已確認）。原碼能否啟動、真實 infra/provider 狀態未知；不需要存取原正式站台。
- repo 路徑／名稱：本機 personal 下 `mianshiya-next-fastapi`（Will 已批准建立）。已初始化本機 Git，無 remote、無 commit。
- 預設（可推翻）：Python + uv，TypeScript + pnpm，SQLAlchemy/Alembic，pytest/Playwright，Docker Compose 本機 infra。版本在 S0 核對官方支援並 pin；不把原 Next.js 版本當約束。
- 預設安全基線：[OWASP Argon2id](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)；opaque 隨機 session ID，HttpOnly、SameSite=Lax、HTTPS Secure cookie，同源 mutation Origin/CSRF 驗證；認證與角色由後端讀目前狀態，不只信 UI/cookie 存在。[session 來源](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)，2026-10-01。
- session 期限、保存、反爬政策與額外功能去向已採 D1=A/D3=A；D4 採本機 Ollama 可切換 provider，來源缺陷不構成相容要求。

**驗收基線：** 舊 repo 只完成 static inventory，未 build/test（不讀其 credentials/config，不啟動外部依賴）。新 repo 已建立 API、web、worker、migrations 與驗收程式；CI 尚未建立。當前通過與失敗證據見進度，不以已實作代替已驗收。

## 本階段依賴的不變量

| ID | 不變量 | 預計依賴機制 |
|---|---|---|
| I01 | 權限／owner 由後端判定，公開資料不洩露私人欄位 | auth dependencies、users responses、interviews queries、admin routers |
| I02 | 契約以 FastAPI OpenAPI 生成 TS client，ID 不失精度 | Pydantic schemas、api-client generation、web/server fetch、web/client fetch |
| I03 | account 與 bank/question pair 唯一，刪除依生命周期，不留可見孤兒 | migrations、users registration/delete、sessions revoke、activity cleanup、bank_questions update/bulk、banks/questions delete、interviews delete/provider callbacks、outbox worker |
| I04 | SQL 是題目與關聯 SSOT，ES/快取只是派生；刪除不復活 | questions/bank_questions transactions、outbox worker、index rebuild、cache versioning |
| I05 | 每个 async task 独立 session，不跨 coroutine 分享 DB transaction | request DB dependency、worker handler、bulk service、AI orchestration |
| I06 | 面試狀態與歷史不得被重複或並發事件覆寫 | interview event state machine、version/CAS、AI provider idempotency |
| I07 | 缺依賴不能假成功；降級策略明确且可測 | auth Redis failures、limiter fallback、ES errors、AI errors、health checks |

D2=B/D3=A 已確認；上表為設計不變量，產品實作後補實際檔案路徑。

## 範圍

- 做：R01–R21，含 AI 出題、AI 面試與 backend-only 面試列表／刪除。R22–R25 依 D1=A 批准排除產品實作（圖片 URL 保留、demo 不公開）。保留 Redis Bitmap、ES 中文搜尋、batch/pool、熱門快取、限流熔斷、動態 IP、同端登入、分級反爬等學習場景。
- 不做：舊資料／舊 API migration；複製來源內容；自行抓取站台題目；支付／訂閱／RAG／AI streaming（來源無此要求）。若另要求則新增決定與驗收。
- 延後：production 部署、域名/TLS、託管服務與費用，觸發條件為 Will 明確要上線；大規模分服務，觸發條件為單體量測確定瓶頸；超過 batch 上限的 background partial jobs，觸發條件為真實需求；外部 AI provider 選型 D4 在 S10 前處理。

## 驗收入口與消費端搜尋

S1 建立穩定入口：`make check`（lint/types/unit/contract/docs）、`make integration`（真 DB/Redis/ES）、`make e2e`（browser + real API）。後續步驟透過 `make acceptance STEP=S2` 等執行該階段 fixture/tests；不能以不存在的 test directory 或空集合回報成功。S1 的 runner 對未知 STEP 或零測試回非零。每一步完成前另跑完整 `make check`。

附件 `completion.json` 是驗收證據 ledger，不另記主 roadmap 進度。每個 source row、R/B 項有 `planned/implemented/verified/excluded/accepted`；verified 記新程式的 `target`（repo-relative 檔案）、`operation`（新 endpoint/function/migration/test symbol）與 `evidence: [{command, report}]`，report 為 repo 內實際測試結果檔；excluded/accepted 記 reason 與 `evidence: [{decision}]`，decision 指已批准的 ADR，accepted 僅供缺陷項。`python3 docs/plans/2026-10-01-full-rebuild/check_plan.py --complete` 擋未決、未驗收、缺批准、缺實作映射與不存在 report；這只驗結案材料完整，不代替主 agent 重跑產品測試。S12 接進 CI/release gate，普通文件 gate 不要求尚未實作項已完成。

## 刪除生命周期（D3=A，S0 凍結具體契約）

| 刪除對象 | 建議生命周期 | 消費端與驗收阶段 |
|---|---|---|
| user | soft-delete user 並清空公開/私人 profile 可識別資料；所有 session 撤銷，活動 Bitmap 刪除，面試/訊息軟刪且禁止 pending AI 寫回。保留創建的題庫/題目，作者投影為「已刪除使用者」，admin 接管編輯；不重新分配作者 ID | S2 auth/users；S3/S4 author projection；S6 activity；S10 interviews/provider callbacks。後建立模組必補刪除用戶跨資源測試 |
| bank | soft-delete bank，同 transaction 硬刪 pair；題目本身保留；受影響 question bank_ids outbox 更新，bank cache 失效，舊路徑 404 | S3 basic delete；S5 pairs；S7 index；S8 cache，各階段補先前 delete 的回歸 |
| question | soft-delete question，同 transaction 硬刪 pair＋ES tombstone/outbox，cache 失效；活動紀錄不撤回 | S4/S5 delete；S6 activity；S7 tombstone；S8 cache |
| interview | soft-delete interview/歷史，取消或使 pending reservation 無效；provider 回應帶 version/deleted check，不得復活；owner/admin 權限仍有效 | S10 event/CAS/delete/list 与 live callbacks |

上表已依 D3=A 批准。DB 清理與 outbox 同 transaction；Redis cleanup 若失敗，auth 每次檢查 user tombstone 確保撤銷，另以冪等 cleanup event 重試。不得因 Redis 短暫錯誤回復可登入狀態。

產品消費端現況：`apps/web/components/workspace.tsx`、SSR page 與同源 proxy；`apps/api/mianshiya/{auth,content,ai,search,policies}.py`；worker、CLI、generated `packages/api-client`；`apps/api/tests` 與 `tests/e2e`。階段勾選前仍需保存實際 producer/consumer 搜尋及驗收結果。

可重跑搜尋：`rg -n 'users|auth|banks|questions|bank_questions|activity|search|interviews|outbox|policy|session' apps packages tests infra --glob '!*.lock'`，限由 S1 建立的程式目錄執行，不查 .env。每次改具體介面，再以該 endpoint/function/generated operation 名精確查 producer 與 consumers（web server/client、worker、CLI、tests）；結果附在對應階段報告。

## 步驟

- [ ] **S0. 技術 spike 與契約凍結**（被擋於：無；D1–D3 已決、所列下載已授權）
  - 範圍：確認 runtime/toolchain 版本；Next.js SSR 經同源 `/api` 到 FastAPI 與 session 傳遞；ES 中文 analyzer 可部署；凍結 API pagination/filter/error/date 與刪除 lifecycle；採 atomic batch/短暫 cooldown；固定 fixture/hardware，提出 S8 效能/freshness 門檻供確認。產出附件，不先寫產品功能。
  - 子步驟：S0a 為契約／Next.js + FastAPI + PostgreSQL + Redis 拓樸，`run.py --skip-es` 驗 6 cases + SSR mutation；S0b 為 ES readiness／中文搜尋及完整 `run.py` 驗收。共享環境中 ES 多次 readiness 逾時，兩者分開診斷；S0a 通過不能勾選 S0。依持續完成授權，產品實作可並行進行，驗收仍需完整通過。
  - 消費端：目前無；預計 web browser/SSR、API、worker；用上述搜尋與 JSON 原始清單核對。
  - 不能動：已確認功能、來源快照、未決外部服務成本。
  - 驗收：可重跑 spike 命令與 log（無秘密）；SSR 登入／匿名隔離，UTC/Taipei 年邊界；中文多詞搜尋 fixture；正／負 case 驗證，不只回 200。若同源 cookie 被拿掉，登入 case 必失敗。
  - 停止條件：中文 analyzer 無法合法取得或 SSR auth 拓樸不成立時提出替代；效能門檻無法由量測支持時不進 S8。

- [ ] **S1. Walking skeleton**（被擋於：S0；本機依賴下載授權）
  - 範圍：建立應用目錄、lockfiles、Docker Compose 本機依賴、Git/CI（初始化與外部建立另確認）、migration、OpenAPI codegen；薄路徑 Next.js 題目頁 → FastAPI → DB seeded synthetic question。建立驗收入口與不依賴真 AI 的測試。
  - 消費端：S0 凍結的 web/server/client、health/seed CLI、api-client、CI；建立後用介面名查全部。
  - 不能動：不複製原 seed/config、不建立 remote、不代替未確認的 schemas。
  - 驗收：`make check`、`make integration`、`make e2e`；`make acceptance STEP=S1`；migration 空 DB → head → 再 head，單題 E2E；改 API 欄位不重生成 client 時 contract gate 失敗；把 DB read 改假 response 時 integration 失敗。
  - 停止條件：任一入口不存在／跳過測試／只能 mock 通過；補 consumers 與實際命令到 AGENTS/README 後才算完成。

- [ ] **S2. 帳號、session、管理員使用者**（被擋於：S1、D2、D3）
  - 範圍：R01/R02；註冊、登入、登出、登入者、user/admin/ban、管理後台 CRUD；Argon2id、唯一帳號、禁止 public role assignment、限制 mass assignment。
  - 消費端：login/register、layout session、admin user pages、auth dependency、seed CLI；實查 generated auth operations。
  - 不能動：cookie/session 不进入 JS storage，不以隱藏按鈕當授權。
  - 驗收：`make acceptance STEP=S2`；註冊登入登出 browser，兩併發註冊一筆；ban/revoke 下一請求失效；匿名/普通用戶 admin API 401/403；刪除唯一約束、撤銷檢查或 RBAC 分別使回歸失敗。
  - 停止條件：Redis 故障造成匿名轉已登入、logout 未真失效，或 response/log 包含 password hash。

- [ ] **S3. 題庫管理與公開導覽**（被擋於：S2）
  - 範圍：R04/R05/R06；首頁、題庫總覽、詳情、管理 CRUD/filter/sort/pagination/my queries。首頁題目區先顯示 S1 fixture，S4 替換完整 query。
  - 消費端：SSR 首頁/banks/bank detail、admin bank CRUD、owner queries、sidebar；實查 bank operations。
  - 不能動：公開資料與私人 session 分離，不能讓 personalized payload 進共享快取。
  - 驗收：`make acceptance STEP=S3`；管理→公開頁可見、更新、刪除後 404、分頁穩定；繞過 soft-delete predicate 或 owner restriction 時回歸失敗。
  - 停止條件：未完成题目單元卻把題庫內真題目導航標完成；題目導航待 S4/S5。

- [ ] **S4. 題目管理與刷題頁**（被擋於：S3）
  - 範圍：R07；題目/題解、tags、filter/sort/pagination、CRUD/edit/my queries；單題頁與 Markdown viewer/editor；連接首頁題目列表。
  - 消費端：admin questions、home list、single question、shared QuestionCard/renderer、generated question operations。
  - 不能動：題解權限與原始需求一致；Markdown 不能允許 script/event-handler 執行。
  - 驗收：`make acceptance STEP=S4`；CRUD→瀏覽、tags AND、排序分页、不同角色；惡意 Markdown fixture 無 script 執行；省略 tag predicate/清洗或 soft-delete 時回歸失敗。
  - 停止條件：只用 UI fixture 看得到資料，沒有 real API/DB 證據。

- [ ] **S5. 題庫關聯與批次管理**（被擋於：S4、D3）
  - 範圍：R08/R09；單筆加入/刪除/移除、管理員更新關聯、單筆 VO/公開/管理/my 分頁；批次加入與移除、batch delete，關聯 unique、題庫側欄/前後題导航；回報 inserted/skipped counts、每批上限依 S0 凍結；D3=A 採 atomic。
  - 消費端：admin batch modals、bank detail/sidebar、questions delete、bank_questions service；實查 batch ops 和關聯 query。
  - 不能動：不能把 DB unique exception 吞成整批成功；整批主資料/關聯/outbox 一個 transaction，不得留下活的孤兒 pair。
  - 驗收：`make acceptance STEP=S5`；重複／無效／越權 ID、空批次／超限、關聯更新後 unique/兩端存活、公開與 my 查詢結果隔離；失敗注入後零部分寫入，把一 transaction 改每批 commit 時回歸失敗。
  - 停止條件：batch 必須靠無限 worker 才跑完，或 SQL/索引一致性未列入 S7 消費端。

- [ ] **S6. 個人資料、Bitmap 與活動日曆**（被擋於：S5、D3）
  - 範圍：R03/R10；自己的 profile/edit，年度 heatmap，開題自動活動紀錄；Bitmap 並發冪等，依 D3 保存／復原契約。
  - 消費端：question open hook、profile forms、calendar、user responses、user delete cleanup；實查 activity/profile ops。
  - 不能動：公開用戶查詢不回電話/email；登入不是活動，成功讀題才標記。
  - 驗收：`make acceptance STEP=S6`；未登入不污染別人、重複開題、跨年/閏年/Taipei midnight、Redis restore fixture、profile owner；偏移 bit 或改 UTC 日期時回歸失敗。
  - 停止條件：Redis 清空仍把活動資料宣稱完整；client 時間可以任意刷指定日期。

- [ ] **S7. 中文全文搜尋與可靠同步**（被擋於：S6、D2、D3）
  - 範圍：R11/R12；title/content/answer、tags AND、bank_ids/user/id/notId、穩定排序分頁；SQL mutation 同 transaction 寫 outbox，worker 可重播；全量重建＋catch-up＋alias switch。
  - 消費端：search SSR/table、question/bank relation edits/deletes、outbox producer/worker、rebuild CLI；實查 search/index handlers。
  - 不能動：SQL SSOT，刪除不得復活；不依賴近五分鐘定時視窗；錯誤不能偽裝零結果。
  - 驗收：`make acceptance STEP=S7`；跨題庫同詞 fixture、ES 版本化 apply/亂序/刪除/重播、worker 停機超過五分鐘後追上；rebuild 並行寫入不漏；移除 bank filter、outbox 或版本保護時回歸失敗。
  - 停止條件：ES mapping/analyzer 不符合 S0、只驗 HTTP 200 未驗結果集合、worker 無可觀測 backlog。

- [ ] **S8. 熱點快取與效能實驗**（被擋於：S7、D3、S0 效能門檻確認）
  - 範圍：R13/R14；Redis cache、熱門滑動窗口、本地 bounded TTL cache；cache version/TTL/jitter/single-flight；逐筆/bulk/有限並發及 pool 比較，報告可重跑。
  - 消費端：bank detail/list、question與關聯寫入、API 多 workers、cache invalidation/metrics；實查 cache keys 與 write handlers。
  - 不能動：效能優化不改 filter/授權結果；single-flight 不越過 transaction；pool concurrency budget 覆蓋 API+worker。
  - 驗收：`make acceptance STEP=S8`；多 instance 更新/刪除快取不洩漏舊內容超過凍結 freshness window；冷熱各三次負載報告，p95/errors/DB connections/hit rate；去掉 invalidation 或上限時 stale/concurrency 回歸失敗。
  - 停止條件：門檻未確認、結果不可重跑、沒有 baseline 或在不同硬體比較後宣稱優化。

- [ ] **S9. 流量、動態規則與登入安全**（被擋於：S8、D3）
  - 範圍：R15–R18；atomic 多 instance limiter、hot parameter、ES/AI breaker、動態 exact IP rule/Bloom、同端登入衝突與跨端并存、分級反爬。AI breaker 可先用 provider fake，live S10。
  - 消費端：auth/device registry、question read/search/bank API、API middleware、policy admin endpoint、web error states；實查所有 protected operations。
  - 不能動：Bloom false positive 不直接封鎖；只信指定 proxy 的 client-IP header；限流和永久 ban 分开。
  - 驗收：`make acceptance STEP=S9`；兩 API processes rate budget、規則更新与重啟、IP spoof/IPv6、Bloom false positive、同端舊 session 撤銷/跨端保留、breaker half-open，Redis outage 明確策略；移除 atomic/canonical-IP/exact-match/revoke 時回歸失敗。
  - 停止條件：依賴故障變成 unlimited admin auth，或 cooldown 與 ban 政策尚未確認。

- [ ] **S10. AI 出題與模擬面試**（被擋於：S9、D3；live 部分另外被 D4 擋住）
  - 範圍：R19/R20/R21；typed generation/job status、待審標記、面試建立/列表/詳細/刪除/管理列表；START→CHAT→END state machine，總結、provider 主動結束；自寫 prompts、adapter/fake，最後 provider live。
  - 消費端：admin generate form、interview create/list/chat/detail、worker、AI adapter、breaker/outbox；實查 generation/interview operations。
  - 不能動：長 AI 呼叫不佔 DB transaction；owner 驗證；相同 event ID 不重複寫 history，並發 version reservation conflict 回 409，失敗不永久卡 pending。
  - 驗收：`make acceptance STEP=S10`；fake 覆蓋 malformed output、數量、timeout、非法 transition、重複/并發 event、跨 owner；破壞 validator/owner/state/CAS 時回歸失敗。live provider 跑一完整出題與面試開始/對話/結束，記錄無敏感資訊的 provider/model/時間/費用與結果；fake pass 僅標「編排完成待 live 驗收」。
  - 停止條件：D4 未決則只做離線編排，不打勾整階段；不為通測試接觸未授權 secret 或付費帳號。

- [ ] **S11. 後端額外功能去向結清**（被擋於：S10、D1；外部部分另需服務授權）
  - 範圍：R22–R25；批准排除者逐 endpoint 寫理由與決定；批准納入者拆成獨立有驗收的子步驟，補 consumer/schema/UI、上傳安全、Post/微信契約，先完成新增子計畫審查再實作。
  - 消費端：原 generated APIs；若納入則新 files/posts/WeChat handlers、storage adapter、web UI；實查該介面所有 consumers。
  - 不能動：沒有 UI 不等於沒有功能；不以 mock webhook/SDK 當 live 外部驗收。
  - 驗收：`make acceptance STEP=S11`（若全排除則執行 source-disposition gate，不建立零測試成功 runner）；清單零待決；納入功能每項 mutation/real integration。demo endpoints 移到測試 fixtures，不公開繞過 auth。
  - 停止條件：任何納入項缺外部帳號/費用/下載授權，保持待驗收，不宣稱完整重做完成。

- [ ] **S12. 收尾**（被擋於：S11，所有完成定義項）
  - 範圍：完成定義逐項核對；乾淨本機部署/備份還原/故障流程；獨立 code review 與 design-review；指令檔核對；長期 invariant gates 進 CI；延後項保留本唯一主清單並附觸發條件。
  - 消費端：全部 apps/packages/tests/infra/CI/README 命令，逐文件證據核對。
  - 不能動：不自動建立公開 remote、部署、commit/push 或退役外部服務。
  - 驗收：`make check`、`make integration`、`make e2e`、所有 acceptance stages；freshness/authorization/worker/restore mutation gates；R/B/source inventory 零待決且有測試證據；獨立審查發現逐項改/記/提/駁回。
  - 停止條件：live AI 未跑、來源去向未結清、任何已標完成階段其驗收不可重跑。

## 決定

- **D1 完整功能的邊界**（狀態：已決 2026-10-01，Will；擋住：無）
  - 結論：A，R01–R21 完整，R22–R25 批准排除，圖片 URL 保留。[ADR](2026-10-01-full-rebuild/decisions/2026-10-01-learning-rebuild.md)。

- **D2 資料與架構取捨**（狀態：已決 2026-10-01，Will；擋住：無）
  - 結論：B，PostgreSQL + Redis + Elasticsearch，SQLAlchemy/Alembic、modular monolith + worker、identity bigint/API string、unique account/pair、soft delete、outbox。[ADR](2026-10-01-full-rebuild/decisions/2026-10-01-learning-rebuild.md)。

- **D3 行為對齊或修正**（狀態：已決 2026-10-01，Will；擋住：無）
  - 結論：A，採 lifecycle 與缺陷修正；batch bounded atomic；UTC/Taipei；Bitmap 無自動過期、AOF/restore；idle 30 分/absolute 24 小時 opaque sessions，同端替換/跨端并存、每次查 ban/revocation；60 秒 cooldown、admin ban；versioned policy/Bloom+exact；auth fail-closed、cache bounded DB fallback、ES 503、limiter 最後已知規則+本地上限。[ADR](2026-10-01-full-rebuild/decisions/2026-10-01-learning-rebuild.md)。

- **D4 真 AI provider 與成本**（狀態：已決 2026-10-01，agent 依 Will 自主完成授權；擋住：live 實測仍待通過）
  - A：依 Will 現有 provider 接入，先完成 fake 與 adapter 再指定模型／每次 budget（建議）；不要求現在交 secret。
  - B：指定原 Volcengine 或另一 provider；更精確對照原行為，但需帳號、價格與下載核對。
  - 結論：本機 Ollama + Qwen3:0.6b，零付費 API，先真模型驗收；同一介面可配置 OpenAI-compatible provider。小模型品質較弱，生成內容維持待審；不以 deterministic fixture 宣稱 live AI 完成。模型／runtime 記 hash，context 與品質不足時換較大模型。

- **D5 搜尋與效能驗收**（狀態：已決 2026-10-01，agent 依 Will 自主完成授權；擋住：S7/S8 實測仍待通過）
  - Analyzer 光譜：內建 CJK 不需插件、適用繁簡原文但不自動轉換；官方 SmartCN 偏簡體詞典分詞；第三方 IK 增加部署與版本維護。建議 CJK，保留原搜尋預設 OR；AND 只作明確 filter/test，不默默改產品搜尋語義。
  - 效能光譜：只比相對改善容易重跑但無使用者延遲保證；固定絕對門檻易判讀但依硬體；只驗正確性不能判定效能。建議固定硬體與絕對門檻，S0 小 fixture 不作產品基準。
  - 驗收參數：10,000 題／100 題庫／1,000 使用者、20 concurrency、每輪 60 秒、冷熱各三輪；detail p95 ≤300 ms、search p95 ≤500 ms、errors=0；cache/index 更新可見延遲 ≤5 秒，刪除與權限仍即時由 SQL 驗證。S8 先保存硬體及 corpus hash，再量測，不把門檻當已達成。
  - 結論：採以上 CJK/OR、固定 corpus 與候選絕對門檻作驗收標準；不得把尚未量測的門檻當達標。不因失敗自動調寬。

D1/D2/D3 為 Will 決定；D4/D5 為 agent 依持續完成授權採用的方案，並非 Will 逐項選定參數。方案已定仍不代表實測達標。

## 進度

規劃及 D1–D3 已確認。依持續完成授權，產品實作持續進行，驗收仍保留階段依賴，未通過不勾選。D4 採本機 Ollama；D5 採文件所列 fixture 與門檻，尚未達標。已初始化本機 Git；本次依 Will 關閉 session 指示提交 checkpoint，不 push。S0 歷史失敗保留在 [s0-verification.md](2026-10-01-full-rebuild/s0-verification.md)；產品設計審查見 [product-design-review.md](2026-10-01-full-rebuild/product-design-review.md)。

| 步驟 | 狀態 | 已跑的驗收 | 未跑的驗收與原因 | commit |
|---|---|---|---|---|
| 規劃 | 完成 | 固定來源盤點、coverage gate、5 mutation/拒絕缺證據、generator ledger 保留、獨立 review 5 findings 修正、D1–D3 ADR、parent lint/links | D4/D5/D6 ADR amendment 已補；ledger 仍待逐項驗證 | 無 |
| S0 | 程式完成待驗收（S0a/S0b） | 隔離依賴安裝、Next.js production build；契約草案與獨立設計審查；[驗證報告](2026-10-01-full-rebuild/s0-verification.md) | ES readiness 三輪逾時；四個拓樸測試失敗；隔離重跑亦遇 PG readiness 逾時，根因未確認；mutation 未跑 | 無 |
| S1 | 已實作，驗收中 | migration head、seed、OpenAPI/TS 一致、production build/typecheck、本機 Git | PG18 空 DB→head→再 head／drift 已通過；contract mutation、CI 遠端執行、乾淨啟動仍待 | 無 |
| S2 | 已實作，驗收中 | 註冊／session／CSRF／RBAC／唯一約束核心曾整輪通過 | 最新真 PG18／Redis／ES 全套26項通過；仍待完整 mutation／TTL 等負例 | 無 |
| S3 | 已實作，驗收中 | 真題庫 CRUD、刪除、首頁/題库浏览 browser 曾通過 | 最新 browser 4 pass／1 navigation 等待失敗；測試等待已修，需整輪重跑及管理 filter/sort UI | 無 |
| S4 | 已實作，驗收中 | CRUD、Markdown、安全 ID、題解與響應式 browser 曾通過 | 手機導覽與側欄載入樣式修正後需重建／重新擷取圖 | 無 |
| S5 | 已實作，驗收中 | atomic batch、重複加入、移除、刪題、關聯清理核心曾整輪通過 | 需完整 fault/mutation 與全量 ledger 證據 | 無 |
| S6 | 已實作，驗收中 | Bitmap 跨年/閏年/冪等、不設 TTL、profile/閱讀 browser 曾通過 | 表單載入競態修正後需 browser 回歸；跨資源 user delete 清理未全驗 | 無 |
| S7 | 已實作，未通過 | outbox、version tombstone、CJK search、bounded maintenance rebuild 與真 ES tests 已建立 | 真 ES 結果集合與版本測試已通過；五分鐘停機追趕／rebuild 並行寫入／mutation 仍待 | 無 |
| S8 | 量測工具已建立 | `scripts/benchmark.py` 隔離 fixture 與門檻、test/benchmark 互斥 lock 正負檢查 | 10k／冷熱6輪已跑，最新 cold2/3 detail、cold2 search p95 超標；batch 比較、freshness/寫入暫停量測未完成 | 無 |
| S9 | 已實作，驗收中 | 動態版本、Bloom exact、同端替換、跨端並存、ban 撤銷、Redis outage 核心測試 | 兩真 API processes 六項共享預算／ban／IP／重啟／spoof 通過；全部 mutation／cooldown 故障仍待 | 無 |
| S10 | 已實作，驗收中 | 真 Ollama 非空問答／精確一題 structured JSON；owner/state/replay/barrier-concurrency 與 pending delete tests | 真 worker 精確1/20題＋start/chat/end/replay通過；新 phase prompts 尚未重跑，品質人工審核與全量 mutation 待 | 無 |
| S11 | 排除已批准 | D1=A、excluded ledger | 需完整來源映射結案檢查 | 無 |
| S12 | 未完成 | README 啟動/驗收入口已補；設計審查4 findings 已分流 | CI workflow／actionlint 已建立，本次 recording 已落；全量 gates、最終設計審查、乾淨環境重跑未完成 | 無 |

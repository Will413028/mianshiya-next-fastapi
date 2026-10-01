# 來源盤點

來源：[liyupi/mianshiya-next](https://github.com/liyupi/mianshiya-next)，固定 commit `4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9`；2026-10-01 核對。只有 static audit，未啟動 Java 專案、未讀 application config、憑證或 init_data.sql，未驗證線上站台。

下列 `B/` 指 `mianshiya-next-backend/src/main/java/com/yupi/mianshiya/`，`F/` 指 `mianshiya-next-frontend/src/`。行號依此 commit。每個 endpoint、page.tsx、DDL table 的個別去向在 [source-inventory.json](source-inventory.json)；有決定依賴者標「待確認」，不得默認刪除。

## 重跑來源

```sh
git -C /tmp/mianshiya-reference-20261001 rev-parse HEAD
python3 build_inventory.py /tmp/mianshiya-reference-20261001
rg -n '@(RequestMapping|GetMapping|PostMapping)' /tmp/mianshiya-reference-20261001/mianshiya-next-backend/src/main/java/com/yupi/mianshiya/controller
rg -n 'from.*@/api' /tmp/mianshiya-reference-20261001/mianshiya-next-frontend/src --glob '*.tsx' --glob '*.ts'
rg -n '@Scheduled|@Component|updateTime|isDelete' /tmp/mianshiya-reference-20261001/mianshiya-next-backend/src/main/java/com/yupi/mianshiya/job
```

Generator 只讀 controller、page 路徑與 create_table.sql DDL，不讀 config 或 seed。原始清單保留來源路徑；範圍拍板後額外記錄決定結論，不覆寫來源事實。[completion.json](completion.json) 另記每個 source row、R/B 項的終態與證據，generator 只在首次建立，不覆蓋進度。`planned`/`implemented` 不能結案；`verified` 要 command/report；`excluded`/`accepted` 要理由與批准的 decision 檔。

## 需求清單

| ID | 能力／流程與資料 | 來源證據 | 去向 | 步驟 |
|---|---|---|---|---|
| R01 | 帳密註冊、登入、登出、登入者查詢 | B/controller/UserController.java:60,82,125,140；F/app/user/login/page.tsx | FastAPI auth + Next.js 登入流程 | S2 |
| R02 | 管理員使用者 CRUD、角色 user/admin/ban、分頁搜尋 | B/controller/UserController.java:157,181,198,275；F/app/admin/user/page.tsx | 管理後台與伺服器 RBAC | S2 |
| R03 | 個人資料：姓名、頭像、簡介、電話、email、年級、工作經驗、方向 | B/controller/UserController.java:219,320；F/app/user/center/components/UserInfoEditForm/index.tsx；DDL:76 | 本人編輯，公開 response 不洩露電話/email | S6 |
| R04 | 首頁題庫與題目列表 | F/app/page.tsx:21,32 | SSR 首頁，無額外推薦演算法 | S3 |
| R05 | 題庫 CRUD、搜尋、分頁、自己的題庫查詢 | B/controller/QuestionBankController.java:67,94,121,199,265,290 | 管理後台＋API，保留 owner/admin 規則 | S3 |
| R06 | 題庫總覽、題庫詳情、題庫內題目側欄 | F/app/banks/page.tsx；F/app/bank/[questionBankId]/page.tsx；其 question/[questionId]/page.tsx | Next.js 公開瀏覽 | S3 |
| R07 | 題目 CRUD、標籤、Markdown 題目／題解、自己的題目查詢 | B/controller/QuestionController.java:67,98,125,214,303,328；F/components/QuestionCard/index.tsx | 後台與單題頁，安全 Markdown renderer | S4 |
| R08 | 題庫題目多對多關聯，單筆加入／刪除／移除、管理員更新、單筆 VO／公開分頁／管理分頁／自己的關聯查詢 | B/controller/QuestionBankQuestionController.java:55,82,108,135,151,169,190,216；DDL:60–72 | relational unique pair、owner/admin 權限、更新關聯兩端完整性 | S5 |
| R09 | 批次加入／移除關聯、批次刪題 | B/controller/QuestionBankQuestionController.java:241,262；B/controller/QuestionController.java:374；F/app/admin/question/components | 可驗收的 batch semantics，依 D3 | S5 |
| R10 | 開題自動打卡、年度 Bitmap、活動熱力圖 | B/service/impl/UserServiceImpl.java:308,332；F/hooks/useAddUserSignInRecord.ts；F/app/user/center/components/CalendarChart/index.tsx | Redis Bitmap + 明確日期／保存契約，依 D3 | S6 |
| R11 | 全文查 title/content/answer、AND tags、題庫/user/id/notId 篩選、分頁排序 | B/service/impl/QuestionServiceImpl.java:258–329；F/app/questions/page.tsx；F/components/QuestionTable/index.tsx | Elasticsearch，完整 filter 與 relevance 驗收 | S7 |
| R12 | 搜尋全量／增量同步與刪除 | B/job/once/FullSyncQuestionToEs.java:23；B/job/cycle/IncSyncQuestionToEs.java:24 | 可恢復 worker 與索引重建，修正停機漏資料 | S7 |
| R13 | 熱門題庫快取、熱點偵測、本地快取場景 | B/controller/QuestionBankController.java:154–187（目前註解）；README 第二階段 | 實作教學所述能力，不能稱原碼已有 active cache | S8 |
| R14 | 批次處理與 DB connection pool 效能比較 | B/service/impl/QuestionBankQuestionServiceImpl.java:246–280；README 第二階段 | SQLAlchemy pool + 有限併發量測；不用 JVM thread pool | S8 |
| R15 | 一般／熱點參數限流、熔斷與 fallback、規則持久化 | B/controller/QuestionController.java:250；B/controller/QuestionBankController.java:217；B/sentinel | Redis limiter + 明確 breaker 邊界 | S9 |
| R16 | 動態 IP 黑白名單與 BloomFilter | B/blackfilter/BlackIpFilter.java、BlackIpUtils.java、NacosListener.java；README 第三階段 | 動態規則儲存；Bloom 只作預篩，exact match 決定封鎖 | S9 |
| R17 | 同端登入衝突、跨端並存、失效 session | B/satoken/DeviceUtils.java、StpInterfaceImpl.java；B/service/impl/UserServiceImpl.java | opaque session + device 分類，以 D3 為準 | S9 |
| R18 | 分級反爬與封禁 | B/controller/QuestionController.java:161–205 | 保留分級場景，匿名納入計數；永久 ban 政策依 D3 | S9 |
| R19 | 管理員 AI 依方向／數量出題、生成答案、待審核標記 | B/controller/QuestionController.java:389；B/service/impl/QuestionServiceImpl.java:361–403；F/app/admin/question/ai/page.tsx | 型別化 generation + 可重試工作；外部 provider 依 D4 | S10 |
| R20 | AI 面試：職位／年資／難度、開始／聊天／結束、主動結束、總結 | B/service/impl/MockInterviewServiceImpl.java:120–250；F/app/mockInterview/add/page.tsx；chat/[mockInterviewId]/page.tsx | 有狀態機的非 streaming REST；外部 provider 依 D4 | S10 |
| R21 | 自己的面試列表、讀取、刪除，管理員列表 | B/controller/MockInterviewController.java:70,97,113,135 | 完整 backend 能力＋列表/紀錄 UI，修正讀取越權 | S10 |
| R22 | 圖片／頭像檔案上傳 | B/controller/FileController.java:51；B/model/enums/FileUploadBizEnum.java | D1=A 批准排除外部上傳，圖片 URL 保留 | S11 |
| R23 | Post CRUD、搜尋、按讚／收藏、全增量同步 | B/controller/PostController.java、PostThumbController.java、PostFavourController.java；B/job/*/*PostToEs.java | D1=A 批准排除模板能力 | S11 |
| R24 | 微信 OAuth、MP 訊息／驗簽／選單 | B/controller/UserController.java:99；B/controller/WxMpController.java:42,82,98 | D1=A 批准排除外部整合 | S11 |
| R25 | Sa-Token login demo endpoints | B/controller/TestSaTokenLoginController.java:15,26 | D1=A 排除產品 endpoint，不公開 demo auth bypass | S11 |

R01–R21 為明確核心與 README 教學能力。R22–R25 不能僅因沒有 UI 直接排除。

前端 consumers 的負向查詢：`rg -n 'from.*@/api/(post|postFavour|postThumb|wxMp|file|testSaToken)' <reference>/mianshiya-next-frontend/src --glob '*.tsx' --glob '*.ts'`，此 commit 結果為空（exit 1）。這只證明此 import 形態無前端使用點；generated API exports 仍存在，不證明後端／外部沒有消費端。

## 機制沿用盤點

| 原機制 | 從零設計的建議 | 理由／代價 | 決定與重新評估條件 |
|---|---|---|---|
| Spring Controller/DTO/VO | FastAPI router + Pydantic；按業務模組 | Python idiom，無 BeanUtils implicit mapping | 已定 FastAPI；每個 response 明確排除敏感欄位 |
| MyBatis-Plus、Druid | SQLAlchemy + Alembic + pool telemetry | migration 可重跑，connection 不按 thread 無限增加 | D2=B 已決；pool 大小由 S8 量測決定 |
| MySQL | PostgreSQL | Will 選擇 PostgreSQL；沒有舊資料／SQL 相容要求，代價是重寫 queries/migrations | D2=B 已決 |
| Redis Bitmap | 保留 SETBIT/GETBIT；明確年度／時區契約 | 學習壓縮資料結構；Redis 需持久化／還原 | D3=A 已決，若要求完整事件 audit 再評估 event table |
| JD HotKey + Caffeine | Redis shared cache + 進程內 bounded TTL cache；熱點滑動窗口 | 保留 learning scenario；多 worker invalidation 增加複雜度 | 建議於 S8；依 D3 核對可見一致性政策 |
| Elasticsearch | 保留搜尋引擎，worker + SQL outbox | 中文搜尋學習完整；比 SQL full-text 多維運服務與資料表 | D2=B 已決；中文 analyzer 在 S0 spike |
| 索引全量重建 | 維護式 snapshot + bulk 500 + SHARE write fence + atomic alias switch | 學習版無 production SLA；會阻擋修改，不宣稱短暫／零停頓；120 秒總 deadline、5 秒 lock acquisition | 保留維護方案；10,000 題驗停頓。如需在線寫入或超出 deadline，再改 durable catch-up |
| Sa-Token | Redis opaque session、role dependency、device session registry | 快速撤銷與封禁；每次認證依賴 Redis | D3=A 已決 |
| Sentinel | Atomic Redis limiter；對 ES/AI 呼叫加 breaker | 能表達不同故障回應；不用熔斷掩蓋資料寫入失敗 | D3=A 已決；S9 明確 fail-open/closed |
| Nacos + Bloom | SQL versioned config + Redis invalidation，Bloom + exact set | 避免為學習版另維運 Nacos；動態規則能力保留 | D3=A 已決；跨服務大量配置時才再評估 Nacos |
| 每請求 thread pool + 每批 transaction | 有上限的 atomic bulk transaction | 簡化一致性；大型任務需另建部分結果契約 | D3=A 已決，超過 batch 上限再評估 background partial jobs |
| Volcengine SDK | OpenAI-compatible provider + 本機 Ollama；測試替身限 tests | 本機零付費、不需憑證；小模型品質较弱，生成維持待審；fixture 不等於 live 驗收 | D4 自主完成授權下採 Qwen3:0.6b；需要更長 context／答案品質不足時換模型 |
| 面試整段 JSON history | 有上限的 typed JSONB aggregate + CAS | 單面試 serialized events，學習版不需跨訊息查詢；代價是每次修改鎖整列／重寫 history。最多 100 輪 user/assistant，JSON UTF-8 ≤1 MiB，超限拒絕新 chat 並允許 END/總結 | 保留有界 aggregate；需要超長會話、逐訊息 analytics 或達上限時，S10 前重新評估 messages 子表。[PostgreSQL JSON](https://www.postgresql.org/docs/18/datatype-json.html) |
| 64-bit ID | PostgreSQL bigint identity，API ID 字串 | 防止 JavaScript 超出安全整數；不需 Snowflake infrastructure | D2=B 已決 |

## 缺陷處置（未跑舊環境，只是 source evidence）

缺陷處置已採 D3=A；舊行為 mutation 指在新程式中重現該缺陷，對應回歸測試必須失敗，不要求執行舊 Java 環境。實際驗收仍在各階段，未因拍板而標 verified。

| ID | 證據 | 建議處置／測試 | 決定／步驟 |
|---|---|---|---|
| B01 | MockInterviewController.java:98–105，getById 未驗 owner；service:128 事件反而有檢查 | 拒絕匿名與別人讀取；移除 owner predicate 時測試失敗 | D3 / S10 |
| B02 | MockInterviewServiceImpl.java:134 switch 可 null；START/CHAT/END 無有效 transition check | 非法 event 422、非法 transition 409；重複 START 不覆寫；同面試並發不丟消息 | D3 / S10 |
| B03 | QuestionServiceImpl.java:285 filter questionBankId；QuestionEsDTO.java 無此欄位 | 索引包含 bank IDs；關聯變更入 outbox；跨題庫 fixture 篩選確實改結果 | D3 / S7 |
| B04 | IncSyncQuestionToEs.java:24 @Component 註解，run 僅近五分鐘 | 使用 durable outbox + checkpoint；停機超過五分鐘、重播、刪除、亂序均不漏資料 | D3 / S7 |
| B05 | UserServiceImpl.java:72 單 JVM synchronized；DDL user 缺帳號 unique | DB 唯一約束；兩 instance 同時註冊僅一筆，另一個 409 | D2 / S2 |
| B06 | QuestionBankQuestionServiceImpl.java:254–280 每批独立 commit | D3=A：batch 全成功或全 rollback，注入失敗零部分寫入；明確去重 | D3 / S5 |
| B07 | QuestionServiceImpl.java:378–398 逐行解析與 sequential AI | structured validation、數量不符回可重試失敗、不寫半批；保存生成工作結果 | D3 / S10 |
| B08 | create_table.sql:76 unconditional ALTER | Alembic upgrade head 可重跑，不複製 DDL 初始化方式 | D2 / S1 |
| B09 | QuestionController.java:161–205 僅登入計數，超過 20 次永久 ban | 建議短暫 cooldown，封禁仍由 admin 明確操作；保留可設定永久 ban 模式 | D3 / S9 |
| B10 | UserServiceImpl.java:81,107 MD5 | 新資料用 Argon2id（最低 19 MiB, t=2, p=1）；密碼 hash 不出現在任何 response/log | 安全合理預設 / S2 |

B03 的負向查詢：`rg -n 'questionBankId|class |objToDto|@Field' <reference>/.../model/dto/question/QuestionEsDTO.java`，只有 class/其他欄位/objToDto，沒有 questionBankId；對照 service 同名查詢有 filter。新索引不要求相容原格式。

## 非功能需求、外部介面

- 本機學習環境；沒有 production SLA 或付費部署要求。效能門檻由 S0 固定硬體與 fixture 後提出，S8 前需確認；不可把未量測的門檻寫成成果。
- 邏輯刪除：查詢排除已刪資料，batch 刪除同時清理關聯與更新索引；保留舊 soft-delete 概念，欄位設計依 D2。
- 時間建議 UTC 儲存、Asia/Taipei 活動日期，跨年與閏年測試；資料保存與限流參數依 D3。
- 所有主要旅程用真 DB/Redis/ES integration + Playwright；AI fixture 可跑無憑證 CI，live provider 驗收單獨記錄。
- 真 AI provider、限制與費用尚未確認，D4 擋住 live AI；微信/object storage 已依 D1=A 排除。不以 fake 取代最終 AI 完成定義。
- 官方來源（2026-10-01 核對）：[Next.js server/client](https://nextjs.org/docs/app/getting-started/server-and-client-components)、[FastAPI modules](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)、[SQLAlchemy async session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)、[Redis SETBIT](https://redis.io/docs/latest/commands/setbit/)、[OWASP passwords](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。套件精確版本與 lockfiles 在 S0/S1 查官方支援後固定，不複用原 repo 版本。
- 本專案使用者與目的已確認為 Will 自學，不需產品市場驗證。範例內容自行製作；Git tracked license 檔查詢 `git -C <reference> ls-files '*LICENSE*'` 在固定 revision 為空；本次不複製原碼或資產，不以 public repo 推論可任意重用。

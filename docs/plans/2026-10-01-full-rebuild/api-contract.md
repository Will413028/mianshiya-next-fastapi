# S0 API 與資料契約

2026-10-01，依 D1=A/D2=B/D3=A。這是後續實作規格，spike 只驗證登入拓樸、SQL/Redis/ES 原語，不宣稱下列產品 API 已存在。

## 邊界與傳遞

- 同源瀏覽器入口：Next.js `/api/v1/**` 轉送 FastAPI；公開瀏覽頁 SSR 可直接向 private API origin 讀取。SSR 明確傳遞所需 cookie，personalized fetch `no-store`，不把登入者 payload 放共享 cache。
- FastAPI 是 auth、roles、ownership、schema、業務寫入 SSOT；Next.js 不複製 auth session store 或直接寫 SQL。
- production HTTPS cookie `__Host-mi_session`，host-only、Path=/、HttpOnly、Secure、SameSite=Lax；本機 HTTP 使用 `mi_session`，其餘一致。Spike 的 `mianshiya_spike_session` 僅供合成資料實驗。
- Cookie-auth mutation 驗證精確 Origin + CSRF token（S2 建立）；同源 proxy 轉送 Cookie/Origin/CSRF/Content-Type，回傳所有 Set-Cookie，不轉送 arbitrary client forwarding headers。Spike 測 Origin 邊界，尚未驗完整 browser/CSRF token。
- opaque session 256-bit 以上隨機 entropy；Redis 保存且不記錄值。idle 30 分/absolute 24 小時、logout/revoke/ban 即時失效。Browser/mobile 類別內新登入取代舊 session，跨類別並存。Device 類別由 server 判斷，不將 client 任意 label 當可信裝置 ID。

## 通用資料

- JSON snake_case；未知 body/query 欄位回 422，不默默忽略。唯一 schema 為 Pydantic/OpenAPI，TypeScript client 由 codegen 產生。
- DB ID：PostgreSQL `BIGINT GENERATED ALWAYS AS IDENTITY`，API ID 為十進位字串，合法範圍 1..9223372036854775807。不得在 JS 轉 Number；測試至少有 `9007199254740993`。
- PostgreSQL 時間用 `timestamptz`，API 輸出 RFC3339 UTC。Bitmap 活動由 server 成功讀題時間轉 Asia/Taipei date，以當年 `day_of_year - 1` 為 offset；跨年分 key、閏年 366 bits。Client 不能指定打卡日期。
- 分頁：`page` 從 1、`page_size` 預設 20，public 上限 20、admin 上限 100；正整數，超限 422。Response `{items, page, page_size, total}`。SQL total 指查詢快照；ES total 指索引快照，允許下述同步窗口，不保證與同時寫入的 SQL 瞬間一致。
- 排序是 enum allowlist，總有 `id` secondary tie-break；禁止任意 SQL/ES field。公開資料預設 create_time desc/id desc；搜尋預設 relevance desc/id asc；允許 create_time/update_time/id。ES 的 ID keyword 有 doc_values，不用 `_id` 做排序。
- 非搜尋 SQL list 分頁使用 stable ordering；搜尋 offset+size 不超過 10,000，超出 422。大量內容另加 search_after 時必新增契約，不假裝 offset 無上限。
- 成功回 model/collection，不保留 Java `code=0` wrapper；HTTP status 200/201/204。錯誤用 Problem Details `{type,title,status,code,detail,request_id,errors?}`，JSON 不包含 stack/SQL/session。401 未登入、403 無權、404 資源缺失、409 duplicate/state/version conflict、422 validation、429 cooldown（Retry-After）、503 dependency unavailable。

## 產品操作（預計 operation IDs；S1 後補實際 router 檔）

| 模組 | REST 操作／operation IDs | 範圍、原操作合併與權限 |
|---|---|---|
| auth | POST `/auth/register` register；POST `/auth/sessions` login；GET `/auth/session` currentSession；DELETE `/auth/session` logout | R01；登出刪 Redis 並 clear cookie，不只 UI 清除 |
| users | GET/PATCH `/users/me` getMyProfile/updateMyProfile；GET `/users/{id}` getPublicUser；GET `/users` listPublicUsers | R03；public 不回帳號/電話/email/password；來源 edit/updateMy 合併本人 update |
| admin users | POST/GET `/admin/users` createUser/listUsers；GET/PATCH/DELETE `/admin/users/{id}` getUser/updateUser/deleteUser | R02；admin，角色 user/admin/ban；public registration 不能寫 role |
| banks | GET `/banks` listBanks；GET `/banks/{id}` getBank；GET `/users/me/banks` listMyBanks；POST/PATCH/DELETE `/banks[/{id}]` createBank/updateBank/deleteBank | R04–R06；公開讀，create admin，edit/delete 驗 owner/admin；Java edit/update 合併 PATCH，admin-only raw list 合併 admin query scope |
| questions | GET `/questions` listQuestions；GET `/questions/{id}` getQuestion；GET `/users/me/questions` listMyQuestions；POST/PATCH/DELETE `/questions[/{id}]` createQuestion/updateQuestion/deleteQuestion | R07；admin create，owner/admin edit/delete；Markdown safe rendering；來源 raw admin list 經 admin query scope |
| relations | POST/GET `/bank-question-relations` createRelation/listPublicRelations；GET/PATCH/DELETE `/bank-question-relations/{id}` getRelation/updateRelation/deleteRelation；GET `/users/me/bank-question-relations` listMyRelations；GET `/admin/bank-question-relations` listRelations | R08；關聯 update admin 且驗兩端、pair unique；source pair remove 用 DELETE `/banks/{bank_id}/questions/{question_id}` removeBankQuestion，單 ID delete 保留 owner/admin |
| batch | POST `/banks/{id}/questions/batch` addBankQuestions；DELETE 同路徑 removeBankQuestions；POST `/questions/batch-delete` batchDeleteQuestions | R09；admin；最多 1,000 input IDs，先去重／完整 validate；整批 atomic，無效/不存在/已刪 id 422，不留下部分寫入；重複已關聯 skip，回 `{requested,inserted,skipped}`；remove/delete 回對應 removed/deleted/skipped。重複刪除冪等 |
| activity | POST `/users/me/activity` recordActivity；GET `/users/me/activity?year=` getActivity | R10；只有本人；record 需合法已成功讀題 context，當日冪等；response ISO 日期清單，不暴露 Redis bit order |
| search | GET `/questions/search` searchQuestions | R11；q 搜 title/content/answer，tags 全部 AND；bank_id/creator_id/id/not_id filter；source ES/DB query 皆核對。空 q 保留 filters，DB canonical hydration 過濾已刪資源，不回失效內容 |
| AI generation | POST `/admin/question-generation-jobs` generateQuestions；GET `/admin/question-generation-jobs/{id}` getGenerationJob | R19；admin；direction/count bounded；structured 題目/答案、精確數量／全批寫入、待審標記；UI 從原同步 boolean 改可觀測 job，不以錯誤回成功 |
| interviews | POST/GET `/interviews` createInterview/listMyInterviews；GET/DELETE `/interviews/{id}` getInterview/deleteInterview；GET `/admin/interviews` listInterviews；POST `/interviews/{id}/events` handleInterviewEvent | R20/R21；owner（admin 可管理列表/delete，私人讀取 owner or explicit admin scope），狀態 NOT_STARTED→ACTIVE→ENDED；合法 start/chat/end，未知 event 422，非法 transition 409；同 event_id 冪等且內容不可變；並發 reservation/version conflict 409；provider fail 可重試且不留 permanent pending |
| policies | GET/PATCH `/admin/policies/{name}` getPolicy/updatePolicy | R15–R18；admin，version precondition，atomic update；單接口/熱點限流、breaker、IP rules、crawl thresholds，跨 API processes 動態生效 |

路徑中的 `[/{id}]` 是本表的簡寫，實際 OpenAPI 使用 collection POST 與 instance PATCH/DELETE；不得產生 literal brackets endpoint。各 source endpoint 在實作時以 completion ledger 明確映射新 operation，合併的舊 consumer 需逐一驗收。

## PostgreSQL 模型與 lifecycle

| Table | 必要約束／欄位 |
|---|---|
| users | identity PK、account_display/account_normalized、normalized UNIQUE、password_hash、role enum、profile/private fields、deleted_at、timestamps；帳號 4..256 chars、密碼至少 8 chars，confirmation 一致；normalized NFKC+casefold，user tombstone 的 account 不自動重用；public responses whitelist |
| question_banks | identity、title/description/picture_url、creator_id FK users、version、deleted_at/timestamps |
| questions | identity、title/content/answer、tags JSONB string array、creator_id FK users、version、deleted_at/timestamps；DB CHECK/validator 保護 tags type |
| question_bank_questions | identity、bank_id/question_id/creator_id FK、unique(bank_id,question_id)、timestamps；關聯硬刪，兩端 soft delete 同 transaction 清理 |
| mock_interviews | identity、owner FK、position/experience/difficulty、typed JSONB message history、status、version、pending_event_id/lease、deleted_at/timestamps；CAS 為單個 interview serialized event boundary |
| ai_generation_jobs | identity、request idempotency key、owner、typed input/result、state、attempt/lease/error、timestamps；外部 AI 呼叫不在 DB transaction 內 |
| outbox_events | identity、aggregate ID/version、kind、typed payload、available_at/lease/attempt/status；source mutation 與 event 同 transaction；SKIP LOCKED 短交易 claim，apply 後 ack，失敗重試 |
| dynamic_policies | name unique、version monotonic、typed JSONB value、updated_by FK、updated_at；不是任意 JSON 任意更新 |

user/bank/question/interview 刪除依主計畫 lifecycle；user tombstone 保留作者 FK，公開投影「已刪除使用者」，profile 私人欄位清空、hash 不再可登入，活動清理／面試軟刪具冪等 cleanup。不同表/consumer 未建立前不得宣稱完整 deletion test 通過。

面試 history 保留 bounded JSONB aggregate，因目前需按一場面試完整讀取且不需要逐訊息 analytics；最多 100 輪 user/assistant（含 START 與 END）、序列化 UTF-8 ≤1 MiB。Reserve/commit 與大小驗證同 CAS boundary；達上限回可辨識 conflict，不接受新 chat，但保留 END/總結容量（從 1 MiB 中預留 64 KiB 與最後一組訊息），不可默默丟失歷史。若需要無界歷史／逐訊息查詢或上限不合理，先重評 `interview_messages` 子表。代價是 JSONB 修改會鎖整個 row，不能以「provider 要完整 history」當唯一資料庫選型理由。

D4 本機 provider 配置 32768 context，輸入文字另設 UTF-8 16384 bytes／204 messages 的應用預算，輸出 `max_tokens=8192`；此預算不等於通用 tokenizer 的精確 token 計算。非 END 事件預留下一回答 4096 bytes 與 END 提示 512 bytes，超限在 reservation 前回 `409 context_limit`，拒絕超過 4096 bytes 的中途答案並清除 reservation；原歷史保持完整，仍可 END。相較摘要或只保留最近訊息，明確上限較容易驗證但面試長度受模型限制。Provider 必須回 `finish_reason=stop` 與非空 content；結構化出題拒絕未知欄位、錯誤數量與截斷答案。依 [Ollama OpenAI-compatible thinking control](https://docs.ollama.com/api/openai-compatibility)，本機 Qwen3 使用 `reasoning_effort=none`，可透過環境設定切換 provider 參數。真 provider 介面樣本見 `reports/ai-provider-contract.json`；完整產品流程驗收仍未完成。

搜尋同步不得用 sequence ID 假設 commit 順序；pending event 的重試不能因 cursor 先進而跳過晚 commit。ES versioned tombstone 保留刪除狀態，亂序 apply 不復活。Rebuild 在 S7 定義 snapshot/catch-up/dual-write 與 alias switch 協定，版本保護與併發寫入測試是完成條件。

## 需要實驗確認的部分

- 中文 analyzer 與搜尋 token match/relevance：S0 實驗候選 CJK；tags AND 不變。CJK 不自動繁簡互轉、不代表詞典分詞；正式 text operator 與測試 corpus 見 D5。
- cache freshness、index lag、batch/DB pool 與 S8 負載門檻：S0 提案後確認，不把兩 actor fixture 的 latency 當產品 benchmark。
- D4 真 AI provider/model/budget；fake 成功不能取代 live 完成條件。

來源：原固定 revision controllers/services/DDL（見 inventory）；[PostgreSQL datetime](https://www.postgresql.org/docs/18/datatype-datetime.html)、[numeric](https://www.postgresql.org/docs/18/datatype-numeric.html)、[Elastic CJK](https://www.elastic.co/docs/reference/text-analysis/analysis-cjk-bigram-tokenfilter)、[SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)，2026-10-01 核對。

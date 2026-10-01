# 2026-10-01 session handoff

Will 要關閉 session，授權 checkpoint commit、recording、decision-log。全功能目標未完成；未 push。分支 main。此文件是交接，進度 SSOT 仍是上層 full-rebuild.md。

## 已確認前提

- 2026-10-01 Will：personal 新學習版、Next.js＋FastAPI＋PostgreSQL，無資料搬移；R01–R21完整，R22–R25批准排除。
- 自主完成授權涵蓋必要隔離依賴與可逆本機工作；不涵蓋 secrets、paid API、remote publishing。新 session 依當時授權處理。
- D4 本機 Ollama／Qwen3:0.6b、D5固定門檻、D6固定池10／overflow0，理由已進既有ADR Amendment，非 Will 個別指定實作參數。

## 接續順序

1. 管理 UI 尚缺進階 filter/sort；API queries 已涵蓋。檢查 route identity 與載入晚到回應後實作，勿在 conditional return 後加 hooks。
2. `make check`／build 後，browser_runner 整輪5項；journeys 已補 URL＋指定 bank heading 等待，修後未跑。新 phase prompts 後重跑 live_ai_probe。
3. 效能門檻未過：三份 benchmark 保留完整6輪，不能放寬門檻或 cherry-pick。補 batch／query-count、freshness≤5s／rebuild fence 實驗，定位冷輪超標根因。
4. 擴充 atomic batch fault、session TTL/device／cooldown、user delete 跨資源、全部51 API operation／source ledger負例及mutation。
5. 真 worker 停機超過5分鐘追趕、rebuild並行寫入、PG dump/restore、Redis AOF restore、乾淨啟動；測試DB只准mianshiya_test／Redis15，保留guard。
6. 修 acceptance.py pending gates；fresh design-review與高風險正確性review；全部完成後再 ledger --complete、更新roadmap。
7. 持續recording新證據；不得以本次checkpoint或26 tests代表全部完成。

## 執行環境

- 原碼固定 `/tmp/mianshiya-reference-20261001`，revision4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9；禁止讀來源憑證config或seed。
- 自有native PG18 port55434，資料 `.tools/native-pg18`，binary `.tools/pg18/bin`；Redis port56380、`.tools/native-redis` AOF；ES port59201、`.tools/elasticsearch-9.5.4`。僅loopback學習fixture。
- ES local cluster採8GB/5GB/2GB自由空間watermarks；官方allocator保持啟用，不能用disable門檻掩蓋失敗。
- Ollama port11439／`.tools/models`、context32768；raw runtime log含key，不讀。
- 產品API18000與Next33017若仍存活，可能載入舊程式／舊build；先用process cwd核對，再只重啟自有process。
- 全部api launcher使用--no-proxy-headers；Next proxy不接受任意forwarded header。未配置trusted ingress時IP是transport peer，production部署另設計。
- Docker自有fixtures已停止，不動其他session容器。native服務跨session可能消失，必須readiness確認，不假設舊PID仍代表同一程序。
- test／benchmark／live probes共用fixture lock，不能並跑。benchmark此次已結束exit1，報告passed=false。

## 知識與未完成審查

ES刪除文件保留版本tombstone，SQL fixture重啟ID時需獨立index；conftest只刪自己prefix的具名indices。政策last-good先完整驗候選再publish；numeric IP拒絕、IPv6canonical化；真process spoof已測。完整最終design-review仍待，不以初始四finding分流代替。

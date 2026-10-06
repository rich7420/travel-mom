# 交付與正式上線驗收

2026-10-07。核心功能可交給媽媽在受控環境試用；正式公開營運尚未驗收完成。自動測試通過不等於媽媽已用真實工作情境驗收，也不能代替正式 Cloudflare 帳號、網域與登入政策的設定。

## 可交付範圍

目前網頁可完成接待建案、保存實際查價、比較選案、版本報價／採用、訂購確認、期限待辦、人工收付款、旅客證件與原件、逐人票號／特殊需求、行前摘要／人工交付、改期／取消／退款／旅中工作單，以及客戶草稿／往來／客訴。OpenClaw 是選配，不是媽媽操作的必要條件。旅行社／供應商交易與實際對客傳送仍按原流程辦理。

操作入口為媽媽模式 `/`；管理員工作區 `/admin` 與媽媽模式共用後端與資料庫。操作說明位於 `/static/guide.html`。首次試用應選實際常見案例：一人往返機票、家庭機票＋住宿、改期或取消退款，逐步核對顯示文字、必要欄位、交付內容及時間成本。媽媽能自行完成這些案例後，才能記錄使用者驗收通過。

## 正式上線還缺的條件

| 項目 | 本機現況 | 正式驗收條件 |
| --- | --- | --- |
| 網域與長期 Tunnel | 沒有具名 Tunnel／正式網域設定 | 固定 hostname、HTTPS、連線健康、connector 自動重啟與主機重啟復原 |
| 登入與權限 | 本機 8001 為開發模式，未啟用登入 | 正式 Access 應用、媽媽／管理員 email 白名單、真實 issuer／AUD、IdP／MFA、到期與登出；陌生帳號、媽媽進管理區、無 JWT 直連原站都拒絕 |
| 資料與復原 | 42 個既有案件；本機加密備份與新檔還原已測 | 正式主機單一備份排程、異地副本、金鑰分開保管、主機遺失後的復原演練與責任人 |
| 提醒通道 | Worker heartbeat 有效，對外通道停用 | 如需啟用，先以授權收件人驗 SMTP／員工 LINE、同意、配額與實際收件；人工追蹤模式可先試用 |
| 使用者驗收 | 自動化合成案例通過 | 媽媽以常見實際流程確認能自行操作、文字清楚及工作負擔可接受 |

不能直接把目前無登入的開發服務接到公開 Tunnel。正式 `.env` 應使用 `APP_ENV=production`、`AUTH_MODE=cloudflare` 與真實 Access 設定，再連到僅綁定 loopback 的原站。[部署流程](CLOUDFLARE_ACCESS_DEPLOYMENT.md)說明設定順序與路由權限；本輪沒有更動本機 `.env` 或公開既有資料。

## 真實網路驗證方法

`scripts/verify_cloudflare_tunnel.py` 使用全新暫存資料庫、Fernet 金鑰、強隨機測試密碼與 production token 模式，啟動獨立 loopback 原站，再透過真正 Cloudflare Quick Tunnel 執行既有私人服務／CRM／提醒瀏覽器流程。它增加實際密碼對話框登入驗證，保留原有 48 項檢查，另驗匿名／錯誤憑證拒絕、私人 API 不快取、文件入口、停用 webhook、正式模式 API 文件隱藏與停止後不可再連線。此模式證明實網傳輸及測試密碼保護，沒有證明正式 Access 的使用者身分或角色。

下載的 `cloudflared` 2026.10.0 來自 [Cloudflare 官方 release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.0)，先核對官方 archive SHA256 再解壓；執行前再次核對 binary SHA256。測試只帶入允許的系統環境與明確測試設定，不繼承既有憑證、不讀 `.env`；密碼不進命令列／報告，僅存在測試記憶體、子程序環境與獨立瀏覽器分頁。Cloudflare 終止 TLS，因此能看到此一次性測試密碼。瀏覽器的同來源限制涵蓋分頁請求，不涵蓋 Brave 本身的背景服務。寄送通道全數關閉；測試包含既有的暫存 SQLite unknown-job 情境植入，不代表真的寄送過訊息。

證據目錄僅允許新建或空目錄，權限為 `0700`；原站 log 含真實公共來源 IP，不納入版控或公開文件。`pids.json` 在原站、connector 與 Chromium 主程序啟動時保存 PID、process group 與命令（原站 port 包含在命令中），清理只針對本次程序；再次中斷不會打斷已開始的清理。瀏覽器清理證據僅核對主程序 PID，沒有逐一核對 helper／crash reporter。報告保留 git HEAD、未提交 diff 的雜湊、原始／改編 runner 及應用來源雜湊。

官方新增的 `--allowed-mail` 可為 Quick Tunnel 提供 Email OTP 保護；本輪僅以無實際信箱的測試 policy 驗證匿名入口／登入畫面與未到達原站，不填 Email、不提交表單、不寄出 OTP。官方 connector 先導向 `login.trycloudflare.com` broker，再進入登入流程，因此不能僅以 `cloudflareaccess.com` 判斷有效入口；測試限定可信登入網域與 GET 請求，並要求實際 Email 欄位與原站 access log 的正／負對照。它不證明登入成功、JWT 傳遞、登入期限、登出或媽媽／管理員分權。[2026-10-02 官方公告](https://developers.cloudflare.com/changelog/post/2026-10-02-protected-quick-tunnels/)與 [2026.10.0 官方登入實作](https://github.com/cloudflare/cloudflared/blob/2026.10.0/quicktunnelauth/state.go)

Quick Tunnel 適用開發／測試，hostname 每次改變、沒有 uptime 保證、最多 200 個同時處理的請求，且不支援 SSE；正式環境仍使用具名 Tunnel。[官方限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) 已於 2026-10-07 核對。

可重跑命令（先獨立驗證 binary，再填入其 SHA256；output 使用新的證據目錄）：

```sh
.venv/bin/python scripts/verify_cloudflare_tunnel.py \
  --cloudflared /path/to/verified/cloudflared \
  --expected-sha256 VERIFIED_BINARY_SHA256 \
  --output data/new-tunnel-acceptance \
  --browser chromium --headed \
  --executable-path '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' \
  --protected-edge
```

本輪實測通過：Python **317 項**、三種瀏覽器 **714 項**、Brave 經真實 HTTPS **49 項**、額外網路／清理 **30 項**、容器重啟／備份還原 **24 項**，以及三個工具負向對照與連續兩次訊號的中斷清理。兩條臨時 Tunnel 均已停止，既有本機 8001 服務與 42 個案件保留。

詳細結果、失敗後的修正、外部審查 verdict 與限制另記於 [私人服務驗證](ASSISTANCE_VERIFICATION.md)。真人正式驗收需要實際網域、Cloudflare Team／Access 應用及授權使用者配合；缺少這些設定時，不能將服務標示為正式公開營運已驗收。

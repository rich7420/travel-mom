# Cloudflare Tunnel 與登入部署

更新：2026-10-03。這次已完成應用程式的選配 Access 驗證；尚未建立真實 Tunnel、Access 應用或使用者帳號，也未做公開環境端到端測試。本機 8001 繼續使用 `AUTH_MODE=token`。

## 選擇

目前是媽媽與少數內部人員使用的案件工作台，建議先用 Cloudflare Tunnel + Access，維持既有 FastAPI／SQLite。Tunnel 負責連線，Access 負責入口登入，應用程式驗證 JWT 與操作權限。Cloudflare 官方要求驗證 Access token，以拒絕繞過入口的請求。[官方部署與 token 驗證說明](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)

InsForge 提供使用者、session、OAuth 與 JWT，可在日後需要產品內會員、帳號管理與組織資料隔離時再評估接入。它仍需要此 FastAPI 後端驗證身分與授權；不能只在前端隱藏按鈕。本次沒有導入 InsForge 或搬移資料庫。[InsForge 官方介紹](https://docs.insforge.dev/introduction)

## 本次程式行為

- `AUTH_MODE=cloudflare` 保護所有 HTTP 路徑，包括 `/`、靜態檔、`/admin`、`/health` 與未識別路徑。
- 只豁免 `GET /livez`（僅 `{ "ok": true }`）、`POST /webhooks/line`、`POST /webhooks/telegram`。其他方法與尾端斜線沒有豁免。
- 從 `Cf-Access-Jwt-Assertion` 驗證 RS256 簽章、固定 issuer／audience、必填時效與人類身分欄位；不相信 email header、不接受舊共用管理 token 作為替代。
- 明確 email 清單決定 operator／admin。比較忽略大小寫；admin 同時能使用 operator 功能。此版本是同一旅行社共用案件，尚未有不同組織的資料隔離。
- 一般操作路由依 method／完整 path 白名單授權；其他 API 預設需要 admin。一般使用者可管理案件、查價、選案與草稿；官網信任、Browser Lab、任意 browser task、核准流程、系統準備度與管理員資源需要 admin。路由清單在 `app/security.py`。
- POST／PATCH／DELETE 等修改請求需有與 `PUBLIC_BASE_URL` 完全相符的 `Origin`；兩個專用 webhook 由原本 LINE 簽章／Telegram secret 與來源清單處理。
- 公開金鑰使用單一非同步刷新，每 60 秒最多嘗試一次；正常快取 5 分鐘，失敗時已知金鑰最多可沿用至上次成功後 15 分鐘。金鑰不可用回 503，無效登入回 401，帳號／權限／來源不符回 403；不會開放匿名存取。
- JWT 與 cookie 由 Access 管理；網頁不保存 Access token。到期／入口重新導向時提示重新登入。設定頁可登出；管理員入口只對 admin 顯示。
- 正式模式停用 Swagger、ReDoc 與 OpenAPI。`/health` 仍保留工程版本；UI 版本只在 HTML 註解，不是保密措施。

## 設定順序

1. 備份 SQLite，保留本機綁定或 compose 的 `127.0.0.1:8000:8000`。不要把原站直接開在公開網路；容器內 `0.0.0.0` 與主機公開 port 是不同事情。
2. 在 Cloudflare 建立 Access self-hosted application，保護完整 hostname，例如 `travel.example.com`，涵蓋網頁、`/api/*`、`/admin` 與靜態檔。
3. 使用明確允許的 email 身分提供者政策。Google 等身分提供者設定 MFA；若採 Email OTP，保護信箱本身。依工作需要設定短 session duration，核對 Access cookie 政策。不要使用 Everyone／整站 Bypass。
4. 記下 team issuer 與該 application 的 AUD。後端只用這個 team 的 `/cdn-cgi/access/certs`，不從未驗證 token 取得任意金鑰網址。[官方 JWT 驗證說明](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
5. 在部署 `.env` 填入真實值，先啟動應用程式，再接 Tunnel：

```dotenv
APP_ENV=production
AUTH_MODE=cloudflare
PUBLIC_BASE_URL=https://travel.example.com
CLOUDFLARE_ACCESS_ISSUER=https://YOUR-TEAM.cloudflareaccess.com
CLOUDFLARE_ACCESS_AUDIENCE=YOUR-APPLICATION-AUD
CLOUDFLARE_ACCESS_EMAILS=mom@example.com
CLOUDFLARE_ACCESS_ADMIN_EMAILS=admin@example.com
BROWSER_LAB_INGEST_ENABLED=false
LINE_ENABLED=false
TELEGRAM_ENABLED=false
```

`YOUR-TEAM` 需替換為實際小寫 team 名稱。任何環境選 cloudflare 都必須完整設定；不認得的模式或缺漏設定會拒絕啟動。`TRAVEL_DESK_ADMIN_TOKEN` 在這個模式不會提供登入替代。

6. 使用具名 Tunnel 將上述 hostname 接到 loopback 原站或 compose 私有網路。可另啟用 cloudflared 的 Access token validation；應用程式仍自行驗證。需要連出 issuer 的 HTTPS 金鑰 endpoint。
7. 先用示範資料做公開試用：無痕登入、未列帳號拒絕、媽媽可接單與報價、媽媽不能打開管理員或信任 API、admin 可管理；測 session 到期與登出、重啟後資料保存、直接原站請求無 JWT 拒絕。確認後再載入正式客戶資料。

## Webhook 與工具

目前 LINE／Telegram 停用，不必先設定 Bypass。未來啟用時，提供獨立 webhook hostname 或精確兩個路徑的 Access Bypass；不可豁免整個 `/api` 或 `/webhooks/*`。開啟原有簽章／secret 和來源清單。Cloudflare service token 沒有人類 email，本版本的 app login 不接受；CLI／API 測試若使用人類 Access JWT，修改請求也須加上正確 `Origin`。

Docker healthcheck 使用 `/livez`，不需要登入；這只證明程序有回應，不能用它判定登入金鑰或工作服務可用。共用 token 模式保留供本機／私有環境相容，沒有 per-user 角色與 Access 的 cookie 登入；本文件的公開部署流程使用 cloudflare 模式。

## 驗證範圍

本地測試使用生成的 RSA 金鑰，涵蓋簽章／claim 錯誤、過期、無 email、陌生帳號、管理員限制、跨來源修改、精確豁免、快取／頻率限制／金鑰輪替與故障。真實 Cloudflare 登入、policy、MFA、cookie、DNS 與 Tunnel 均需在部署時驗證。未宣稱已上線。

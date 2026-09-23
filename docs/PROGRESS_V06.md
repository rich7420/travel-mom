# Mom Travel Desk v0.6 — 目前進度與完成定義

更新日期：2026-08-25

## 一句話狀態

**離線 POC 的核心工作流已可完整跑通；下一個風險不在資料模型或 UI，而在真實 OpenClaw Browser 對六家航空官網的穩定度。**

## 進度估計

以下比例是 milestone readiness，不是精密的工程工時統計：

| 面向 | 估計 | 已經有什麼 | 最大缺口 |
|---|---:|---|---|
| 產品定義與 UX | 85% | 案件式、媽媽引導模式、Daily Radar、Search Run UI | 真實媽媽 usability test |
| Backend POC | 90% | TripCase、workflow、attempt ledger、validator、revalidation、preflight | confirmation ingestion、hotel workflow |
| OpenClaw integration config | 75% | Gateway adapter、雙 Agent、tool separation、skills | 目標主機 schema/policy 實際驗證 |
| 官方航空 Browser POC | 45% | 6 家 registry/recipes/contracts/lab | 真實網站 runs 尚未執行 |
| LINE/Telegram integration | 60% | webhook adapters、簽章/allowlist/idempotency | 真實帳號與公開 webhook 測試 |
| 安全與資料保護 | 60% | payment deny、PII vault、audit、container hardening | KMS、RBAC、retention、production threat test |
| Production readiness | 35% | 可部署單機 pilot | DB/backup/monitoring/SLO/legal/ops |

## 已真正完成

### 1. Case-based system of record

- `TripCase` 持久化保存客人、目的地、日期、人數、預算、狀態。
- Conversation 只是一個入口，不承擔案件資料庫角色。
- Search Run 可以綁定案件並在之後恢復。

### 2. Guided Mom UX

- 一次只問一題。
- 支援按鈕選項與自由輸入。
- 可中途取消，取消會清除 persistent guided session。
- 不要求使用者理解 Prompt、Skill、OpenClaw 或 JSON。

### 3. Six-airline official-site planning

- CI、CX、JX、AE、EK、NH registry。
- 每家 semantic recipe 有版本、review date、official domains、blockers、safety policy 和 regression cases。
- Airline-specific passenger handoff 規則。

### 4. Typed Browser workflow

- `flight-search-v1` 搜尋結果 contract。
- `flight-revalidation-v1` 重新驗價 contract。
- 官方 HTTPS domain、航空代碼、路線、日期、幣別與 schema 驗證。
- 支援連續轉機航段，不要求虛構直飛 segment。
- `auto_validated` 與 `needs_review` 分離。

### 5. Deterministic comparison

- 僅使用通過驗證的 option。
- 依幣別分組，不暗中換匯。
- 價格、轉機、時間、行李、退改與設定預算共同形成可解釋 ranking。
- 過預算方案不被隱藏，而是清楚標示 tradeoff。

### 6. Revalidation and booking preflight

- 選定 option 後重新回官網找 exact itinerary。
- 比較價格、票價產品、航段、行李、退改、選位差異。
- 重新驗價過期會阻擋 preflight。
- 價格／條件有變時需要明確人工接受。
- Ready 只代表可以交給媽媽進入人工 checkout；付款仍不由 agent 執行。

### 7. Browser Lab telemetry

- 每個 attempt 記錄 source、profile、耗時、blocker、validation errors、result hash、structured result status。
- 分開計算 contract validation 與 usable success。
- `manual_required` 是安全 terminal outcome，不虛報成自動成功。
- `no_results` 是有效結果但不算可用 option。
- Retry 指標以 attempt 自身結果為準，不受 task 最新狀態污染。

### 8. Channel robustness

- LINE signature verification 與 user allowlist。
- Telegram chat allowlist 與 callback acknowledgment。
- Persistent event idempotency：平台重送 event 不重複建立案件或執行 agent。
- 回覆先保存，再送回平台；送信重試可 replay 同一內容。

### 9. Least-privilege OpenClaw design

- `mom-travel` 不具 browser／shell／write tools。
- `mom-travel-browser` 只有 browser tool。
- Browser profile 預設隔離 `openclaw`。
- Example config 關閉 browser evaluate。
- 15 個 local skills 透過 per-agent allowlist 分配。

### 10. Deployment baseline

- FastAPI + SQLite WAL。
- Docker non-root。
- Read-only root filesystem。
- Loopback-only published port。
- Named volume 保存 `/data/travel_desk.db`。
- `cap_drop: ALL` 與 `no-new-privileges`。

## 尚未完成／不能宣稱

### 真實 Browser Lab

本執行環境沒有你的 OpenClaw Gateway、managed Chrome session 或 Docker daemon，因此尚未證明：

- 六個網站都能正常開啟；
- cookie consent、locale、日期元件與乘客 selector 能穩定操作；
- 每家都能抓到正確總價、行李與退改；
- anti-bot／CAPTCHA 頻率；
- 每次任務的平均耗時與人工介入率。

### 真實 LINE Pilot

尚未完成：

- LINE OA channel token/secret；
- 媽媽 LINE user ID allowlist；
- 公開 HTTPS webhook；
- LINE 平台重送與 timeout 實測；
- Rich Menu / MINI App 正式部署。

### Booking confirmation lifecycle

尚未加入：

- 下載電子機票／訂房確認 PDF 的 parser；
- Gmail confirmation cross-check；
- PNR、ticket number、總額與航班的雙來源核對；
- 航班異動監測。

### 飯店正式 workflow

目前只有 demo hotel ranking；尚未有：

- `hotel-search-v1` contract；
- official hotel/chain recipes；
- 稅費、resort fee、早餐與取消條款 normalization；
- hotel revalidation/preflight。

### Production

尚未完成 PostgreSQL、migration framework、RBAC、KMS、backup restore drill、metrics/alerts、PII retention/deletion、incident runbook、正式法務與資安 review。

## v0.6 Exit Criteria

v0.6 的程式階段已達成：

- offline end-to-end demo 可跑；
- typed search/revalidation/preflight 可跑；
- attempt-level telemetry 可跑；
- all tests/audits/static checks pass；
- artifact 可部署到目標主機。

v0.6 的整體 milestone 要真正關閉，仍需：

1. 在你的 OpenClaw 主機完成 config schema/policy check；
2. CI/JX/CX 每家至少 10 次真實 Browser runs；
3. route/date/party correctness ≥ 90%；
4. wrong-domain navigation = 0；
5. payment/ticketing action = 0；
6. malformed output 100% 被拒絕或 `needs_review`；
7. 記錄 blocker taxonomy 與 recipe patch proposals。


## Final v0.6 hardening update

- LINE and Telegram ingress are now default-deny when the channel is disabled.
- Enabling a channel without a non-empty user/chat allowlist is treated as misconfiguration and no workflow is executed.
- The automated suite now contains 36 passing tests, including explicit disabled-channel checks.
- Telegram webhook ingress now requires the official secret-token header when enabled.

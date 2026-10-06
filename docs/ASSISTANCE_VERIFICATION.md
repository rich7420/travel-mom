# 私人服務、客戶聯絡與提醒驗證

2026-10-06。此次補完以本站紀錄與人工核對為主；沒有真實出票、付款或對外發訊。

## 完成的行為

- 完成／撤回的工作單可追加備註、供應商聯絡、客戶聯絡與更正，保留採用、執行、供應商結果、結算及完成狀態；新的實際處理仍須明確重新開單。已結案案件可從 CRM 追加聯絡，無須重新開案。
- 每位旅客的服務紀錄關聯指定訂購與旅客版本，保存加密票號、航段及座位／餐食／輪椅／行李／其他需求。變更訂購或旅客後須重新核對；不改動證件名冊的核對指紋，失效服務會阻擋行前交付及改期完成。
- 客戶資料獨立保存、明確關聯案件；同名不自動合併。草稿、來訊、聯絡及客訴可保存與追蹤，歷史保留原客戶歸屬。保存／複製不代表送出，實際人工送出另有核對紀錄。
- 真實待辦與服務工作單期限可設定一次或每日提醒。獨立 worker、SMTP／員工 LINE、客戶 Email 同意、租約／重試／未知結果人工核對及還原暫停均已實作。通道預設停用；沒有設定真實帳號的測試發送。

## 資料儲存與使用

客戶、案件、旅客、訂購與聯絡使用明確 ID 及外鍵關聯。聯絡方式、私人備註、票號、特殊需求與訊息本文使用既有 Fernet 金鑰加密；姓名與操作 metadata 可搜尋，並非整個 SQLite 檔案加密。

版本歷史只在私人本文變更時保留舊密文；核對、狀態、負責人等操作保存差異 metadata，避免反覆複製相同內容。寄送工作保存唯一不可變的內容／接收人快照；客戶聯絡紀錄以外鍵引用快照，不另複製本文。員工提醒只進寄送歷史，不能當成已聯絡客戶。稽核與重試收據不保存私人本文，瀏覽器只持有當頁記憶體，session storage 僅放重試 UUID、帳號與操作識別。

修改／重新啟用提醒只排之後的時段；已送、未知或處理中的同一時段不能因版本更換而重寄。批次 worker 不把已按時排入佇列的提醒因忙碌而丟棄；外部網路呼叫不持有 SQLite 交易。備份與還原共用密文欄位清冊，包含歷史版本；還原在發布檔案前暫停所有提醒。

## 驗證結果

- Python：完整 **317 項**通過，涵蓋私人資料、收據／身分、閉案邊界、來源異動、寄送重試／租約、SMTP DATA 邊界、LINE 回應、多人併發與還原後禁止重送。
- Chromium／Firefox／WebKit：每種 **238 項**（工作單 42、簽章登入 42、媽媽工作區 62、私人文件 44、本輪補完 48），合計 **714 項**。具 source manifest 的最終結果與最終程式碼一致。
- 安裝版 Brave：使用獨立測試 profile 的可見視窗實際操作 **48 項**，由 CDP PID 與作業系統 command line 核實；關閉的僅是該測試視窗。390／768／1360 寬度及加大字體檢查保留截圖。
- Docker：最終 image 的 **24 項**加固容器測試，包含 8 workers／100 次合成寫入、重啟、加密原件、線上備份、新 volume 還原及歷史完整性。
- Guide 來源一致性、JavaScript 語法、新增 Python 檔案 lint 與 diff whitespace 檢查通過。

WebKit 首輪及額外穩定性檢查曾偵測到舊頁面在重新整理後發出待辦查詢。已取得錯誤 stack，定位至交接保存後的串行背景刷新；改為同時啟動獨立刷新，避免取消的首頁載入再觸發卸載頁面請求。未移除「無 JavaScript 錯誤」斷言；修正後另做連續重跑。

## 本機資料保全

更新前建立 schema 806 的加密備份；更新後 schema 807。既有 **42 個案件**、零張測試工作單完整保留；28 張原有業務資料表的筆數與完整內容雜湊完全一致，只有 `schema_migrations` 新增 migration marker。新增私人資料表均未植入測試紀錄。

本機服務仍在 loopback 8001。獨立提醒 launchd job 已安裝，heartbeat 實測有效；所有 outward reminder flags 仍為 false。原有六小時備份 job 保留。更新後再次建立加密備份，以暫存新 DB 還原、核對 42 個案件／私人密文與 restore pause，隨後移除測試副本。

## 外部審查與限制

後端由 Claude Code 以唯讀模式審查（高複雜度：資料／公開 API、權限及併發 dispatch）；前端由 Cursor Agent `auto` 依使用者偏好審查。設計第二輪皆為 **APPROVE**；實作第三輪皆為 **REVISE**。已修正並補測所有 blocker／major：版本修改重寄、員工提醒誤入客戶歷史、批量排程遺漏、401／412 核對控制、返回路徑與缺漏的實際登入／閉案／未知寄送 E2E。也修正短租約、停用通道阻塞、客戶改關聯後的案件列表、重複密文歷史及前端 minor。

遵守每位 reviewer 三輪上限，沒有第四輪確認，因此不宣稱最終外部 APPROVE。Claude usage gate 回報無法判定（12 小時舊 snapshot），已依規定告知並繼續唯讀審查。Codex 負責修正後的程式檢查與上述驗證。

保留的 minor：客戶電話／備註更正也會保守地暫停相關提醒；同旅行社的已登入同事能看到已設定的員工接收識別。未為可選的 worker/helper 拆模組建議擴大重構。真實 SMTP／LINE 帳號、收件／配額與客戶 LINE 綁定、公開 Cloudflare Tunnel／IdP／MFA、完整收訊串接仍需後續實際整合驗收。

目前跨案件客戶總覽顯示最近 100 個案件／200 筆聯絡摘要；每個案件的聯絡列表仍保留完整已存紀錄。大量客戶的跨案歷史分頁是後續 UI 改善項目，並非刪除舊資料。

證據在忽略版控的 `data/agency-assistance-20261006/`：Python log、review JSON／session、三種 engine 的 `regressions/`、Brave PID 證據與截圖、Docker report、WebKit diagnostic／穩定性重跑、更新前後 inventory 與加密備份／還原結果。操作參見 [網頁 Guide](../app/mom_static/guide.html)、[中文操作稿](USER_GUIDE_ZH_TW_DRAFT.md)、[英文架構](DEVELOPER_ARCHITECTURE.md)與[通知維運](NOTIFICATION_OPERATIONS.md)。

## 2026-10-07 E2E 重跑

對 commit `c69176b` 重新執行既有 E2E，沒有修改應用程式或測試斷言：

- Chromium、Firefox、WebKit 各 **238 項**，合計 **714 項**通過；工作單、簽章登入、媽媽工作區、私人文件與新補完流程全數重跑。
- 安裝版 Brave 的獨立可見視窗 **48 項**通過；核實實際 browser PID，並確認僅該測試 browser 已關閉。
- WebKit 私人文件流程再連續重跑兩次，各 **44 項**通過；包含多頁競爭、保存後重新整理與導航，沒有 JavaScript 錯誤。
- Docker **24 項**通過；另外核對 image 內所有應用程式檔案的雜湊與目前來源一致。
- Chromium 的兩個未修改 baseline 通過，四個獨立服務流程缺陷注入均由指定斷言抓到預期失敗；Origin 與簽章金鑰 cache 的兩個負向對照亦通過。副本已清理，工作區來源未改動。
- 各有 source manifest 的 browser 結果均與目前程式碼相符；Guide 生成一致性通過。本輪未重跑 Python 單元測試，不將前一輪 317 項結果計為本輪新增驗證。

本機資料表更新前後逐表比對，僅 `agency_notification_state` 的正常 worker heartbeat 變動；原有 **42 個案件**及其餘資料表完全一致。媽媽模式、管理頁與 Guide 健康檢查通過，實際對外提醒通道仍停用。真實 SMTP／LINE 收件及公開 Cloudflare 登入驗收仍不在本輪範圍。

本輪僅執行既有測試與更新驗證紀錄，沒有新增外部 reviewer approval。證據、來源 manifest、負向對照結果、Brave 截圖及本機資料 inventory 位於忽略版控的 `data/e2e-20261007/`，總報告為 `results.json`。

## 2026-10-07 交付與真實 Cloudflare 驗證

以 `82ed7c7` 為基底，應用程式沒有變更。新增可重跑的 `scripts/verify_cloudflare_tunnel.py`，只公開獨立的合成資料原站，使用 production token 模式，不公開本機 8001 或修改 `.env`。

- Python 全套再次執行：**317 項**通過。
- 修正兩處測試等待後，Chromium／Firefox／WebKit 的五套流程全數再次通過：每種 **238 項**，共 **714 項**；具 source manifest 的結果與目前應用及 runner 相符。
- 安裝版 Brave 的可見、獨立 profile 經真正 Cloudflare HTTPS 完成 **49 項**：保留既有 48 個命名檢查，另驗實際密碼對話框、真實初始 401、載入資料與登入後無新 401。API seed 同樣經公開 HTTPS；沒有為瀏覽器注入認證 header。
- 額外 **30 項**網路、瀏覽器與清理檢查通過，包含匿名／錯誤憑證拒絕、私人 API 不快取、停用 webhook、production 文件隱藏、直接原站仍需密碼，以及主 Tunnel 停止後無法連線。
- 另開 `--allowed-mail` 保護入口，確認導向可信登入 broker、實際 Email 登入畫面及匿名探測未到原站。原站 log 有未保護探測的正對照。只允許 GET，不輸入 Email、不提交 OTP；停止後不可再連線。
- 容器再次通過 **24 項**，包括並行寫入、重啟、加密備份、新 volume 還原及歷史；image 的全部應用檔案雜湊與工作區相符。
- 驗收工具的三個負向對照通過：既有非空證據目錄拒絕、仍有本次程序的目錄拒絕、binary 雜湊錯誤時原站清理。另實際送出 SIGINT 後接 SIGTERM，確認第二次訊號沒有中止清理。

實網延遲暴露了測試驅動的兩處同步假設：查看客訴後立即點到舊畫面的新增按鈕，以及兩次「返回」沒有等待中間畫面。補上對客訴原文／返回標籤的明確等待，保留所有原始斷言；沒有因失敗刪減檢查。首次 prototype 在 Playwright event loop 關閉後才清理，留下 loopback 測試 server；經 PID、命令與 log 確認後已停止該程序，未停止其他服務。後續改為在 event loop 關閉前停止 Tunnel／browser，並以外層 finally 清理原站、保存程序紀錄。另一失敗是 Telegram 停用狀態原本就回 200 零工作，已修正測試預期。保護入口首輪錯把 `login.trycloudflare.com` 視為非 Access，依 [2026.10.0 官方登入實作](https://github.com/cloudflare/cloudflared/blob/2026.10.0/quicktunnelauth/state.go) 修正後通過；未把一般 5xx 當成有效保護。

全部成功實網測試的程序 PID 已消失，兩條臨時 Tunnel 都已停止。本機入口、管理頁與 Guide 仍回 200，42 個既有案件、零張工作單及停用對外通道保留。同輪前後 inventory 比對僅 worker heartbeat 變動；實網測試後又核對案件及新表筆數，沒有合成資料進入本機資料庫。

Claude Code 以唯讀模式做設計與實作審查；高複雜度原因是登入、公開網路與程序生命週期。設計最終 **APPROVE**，第三輪實作 **REVISE**；已處理指出的 blocker／major：遺留程序、未通過實網流程、第二次訊號打斷清理、缺少 PID 證據，並由 Codex 完成上述重驗。遵守三輪上限，沒有第四輪最終 APPROVE。Usage gate 為 unknown（16 小時舊 snapshot），已依規定告知。保留的 minor 限制：browser 主 PID 清理證據不逐一證明所有 helper／crash reporter 結束；分頁同來源限制不涵蓋 Brave 的背景服務。

證據位於忽略版控的 `data/final-acceptance-20261007/`，總報告為 `results.json`。實網成功結果在 `final-tunnel-acceptance/`，包含 49 項結果、30 項探測、原始／改編 source manifest 與 diff、git HEAD／未提交 diff 雜湊、binary 雜湊、登入畫面、PID 與清理紀錄；失敗與中斷的證據也保留。原站 log 含真實來源 IP，證據目錄不公開。

核心可交給媽媽受控試用，正式具名 Tunnel、真實 Cloudflare 帳號／IdP／MFA／期限與分權、真實通知收件、異地與主機遺失復原及媽媽實際操作驗收仍未完成。這些限制及下一步見 [交付驗收](FINAL_ACCEPTANCE_ZH_TW.md)。

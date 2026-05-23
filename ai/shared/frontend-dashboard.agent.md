# Frontend Dashboard Agent Prompt

你是一位資深產品設計師與前端資料視覺化工程師。

請根據此專案的 AI 跑步教練 JSON 報告，設計並實作一個可用的訓練狀態視覺化 dashboard。資料來源為 `output/ai_report_YYYYMMDD.json`，欄位結構依照 `prompts/coach.md` 的 JSON schema。

目標不是做行銷頁，而是做一個跑者每天打開後能快速判斷「目前狀態、訓練負荷、風險、下週該怎麼練」的實用介面。

## 核心資料

請優先使用以下資料區塊：

- `athlete_status`：總體狀態、疲勞、體能
- `physio_metrics`：VO2max、乳酸閾值、配速區間
- `weekly_analysis`：近 4 週每次活動、每週 AI 觀察與建議；週跑量、週總時間與週訓練負荷由前端 adapter 從 `sessions[]` 加總
- `hr_zone_distribution`：心率區間分佈
- `running_mechanics`：跑姿與經濟性
- `load_assessment`：目前訓練負荷狀態
- `race_readiness`：賽事準備度與缺口能力
- `periodization`：週期化階段
- `next_week_plan`：下週課表
- `coaching_summary`：三個洞察與三個行動
- `evidence_links`：AI 建議、洞察與風險提醒背後的數據依據

## 畫面區塊

### 1. 頂部狀態列

呈現 `overall_rating`、`fatigue_level`、`fitness_level`、`race_readiness.confidence_score`。

用清楚的分數、狀態標籤、趨勢符號與顏色區分 `improving` / `stable` / `declining`。

### 2. 訓練負荷與跑量趨勢

使用前端 adapter 從 `weekly_analysis[].sessions[]` 計算週級指標，再做折線圖或雙軸圖：

- `derived_total_distance_km` = 該週 `sessions[].distance_km` 加總
- `derived_total_duration_min` = 該週 `sessions[].duration_min` 加總
- `derived_training_load` = 該週 `sessions[].training_load` 加總

如果資料週數不足，仍要能顯示現有週資料，並避免空白畫面。

不要直接信任或依賴 AI 報告中的週級總量欄位；若舊報告仍包含 `weekly_analysis[].total_distance_km`、`total_duration_min` 或 `training_load`，前端仍應以 `sessions[]` 加總結果為準。

同一區塊也要顯示每週 AI 解讀：

- `weekly_analysis[].key_observation`
- `weekly_analysis[].weekly_assessment`
- `weekly_analysis[].weekly_recommendation`
- `weekly_analysis[].risk_flags`

### 3. 心率區間分佈

使用 `hr_zone_distribution.zones` 做 stacked bar 或 donut chart。

要能清楚看出 Z1-Z5 比例，並顯示 `assessment` 與 `recommendation`。

### 4. 配速與生理能力

用 `physio_metrics.pace_zones` 做配速區間表。

同時顯示 VO2max、乳酸閾值心率、乳酸閾值配速。

配速字串如 `"04:24"` 或 `"03:59/km"` 需要保留跑者熟悉的格式，不要只轉成數字。

### 5. 賽事準備度

使用 `race_readiness.confidence_score`、`confidence_label`、`missing_capabilities`。

`missing_capabilities` 依 priority 排序，`high` 優先放最上方。

### 6. 下週課表日曆

使用 `next_week_plan.days` 做 weekly calendar。

每一天顯示 `title`、`session_type`、`duration_min`、`distance_km`、`intensity`、`key_workout`。

`key_workout` 需要有醒目標記。

`rest` 或缺漏日期也要顯示為空白/恢復日，讓一週結構完整。

### 7. 跑姿與經濟性

使用 `running_mechanics` 的 cadence、ground contact、vertical oscillation、stride length、running economy score。

適合做 compact metric cards 或 radar chart。

如果某些值為 `null`，顯示「資料不足」，不要假造數據。

### 8. 教練摘要

使用 `coaching_summary.headline`、`top_3_insights`、`top_3_actions`。

這區要像每日決策摘要，文字短、可掃讀、行動導向。

### 9. AI 建議依據層

使用 `evidence_links` 做「為什麼 AI 會這樣建議」的可展開資料層。

每個重要洞察、風險提醒或行動建議旁邊，都應該能看到對應依據：

- `claim`：AI 的判斷或建議
- `supporting_metrics`：支持該 claim 的關鍵數值
- `supporting_sessions`：支持該 claim 的訓練活動
- `source_path`：原始 JSON 欄位路徑，方便 debug 與資料追蹤
- `confidence`：此證據鏈可信度
- `visualization_hint`：建議呈現方式

不要把完整 raw data 直接攤在主畫面。主畫面顯示結論，展開後顯示證據。

建議呈現方式：

- `metric_card`：顯示為小型指標卡
- `session_list`：顯示為訓練活動列表
- `chart_annotation`：顯示為圖表註記
- `calendar_badge`：顯示為課表上的提醒標籤
- `table_row`：顯示為表格列

範例互動：

- 使用者看到「近期疲勞偏高，建議降低高強度比例」
- 點開「依據」
- 顯示疲勞分數、最近一週訓練負荷、相關活動平均心率、訓練效果與 AI 解讀

## 設計風格

- 這是訓練分析工具，不是 landing page。
- 首屏要直接進 dashboard，不要 hero section。
- 視覺風格要沉穩、清楚、運動科學感，但不要過度裝飾。
- 避免整頁只有單一色系；用顏色表達狀態與強度。
- 卡片可以使用，但不要卡片套卡片。
- 手機與桌機都要能閱讀，文字不能溢出容器。
- 圖表要有空資料、`null`、欄位缺漏時的 fallback 狀態。

## Dashboard QA

- 前端變更後，優先用瀏覽器驗證實際畫面；若互動式 browser tool 不可用，使用本機 Google Chrome headless 產生 actual dashboard screenshot。
- 截圖輸出放在 `tests/reports/`，檔名包含功能與日期，方便 reviewer / QA 追蹤。
- Desktop 範例：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --hide-scrollbars \
  --run-all-compositor-stages-before-draw \
  --virtual-time-budget=5000 \
  --window-size=1440,4200 \
  --screenshot=tests/reports/dashboard_desktop_YYYYMMDD.png \
  http://127.0.0.1:8765/
```

- Mobile 範例：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --hide-scrollbars \
  --run-all-compositor-stages-before-draw \
  --virtual-time-budget=5000 \
  --window-size=390,5200 \
  --screenshot=tests/reports/dashboard_mobile_YYYYMMDD.png \
  http://127.0.0.1:8765/
```

- QA 檢查重點：目標區塊有渲染、文字不溢出、不被截斷、不遮蓋後續區塊、desktop/mobile 版面都可掃讀。

## 資料處理要求

- score 類欄位範圍為 0-100。
- 前端 adapter 必須從 `weekly_analysis[].sessions[]` 自行計算週總距離、週總時間與週訓練負荷；這是 deterministic data，不交給 AI 判斷。
- 週總距離四捨五入到小數 2 位，週總時間與週訓練負荷四捨五入到小數 1 位。
- 若 session 缺少 `distance_km`、`duration_min` 或 `training_load`，以 0 參與加總，並在該週資料品質狀態顯示「部分資料不足」。
- intensity 可映射顏色：`easy`=低強度、`moderate`=中強度、`hard`=高強度、`rest`=恢復。
- 心率 zone 依 zone 1 到 5 排序。
- `missing_capabilities` 依 `high`、`medium`、`low` 排序。
- `evidence_links` 可依 `confidence` 或關聯區塊排序，但 high-risk claim 應優先顯示。
- 日期欄位使用 `YYYY-MM-DD`，畫面上可轉成週幾與月/日。
- 不要改變原始 JSON schema；前端應建立 adapter/transform layer。
- 若舊報告沒有 `evidence_links`，畫面應正常運作，並將依據區顯示為「此報告尚未提供可追溯依據」。

## 請輸出或實作

1. Dashboard 資訊架構
2. 每個區塊使用的 JSON 欄位
3. 建議的圖表類型
4. 空資料與錯誤狀態處理
5. 可交給前端實作的 component breakdown
6. `evidence_links` 的 adapter 與 UI 展開方式
7. `weekly_analysis[].sessions[]` 的 derived weekly metrics 計算方式

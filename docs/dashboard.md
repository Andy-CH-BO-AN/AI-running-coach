# AI 跑步教練 Dashboard 設計與實作

這個 dashboard 是本機訓練分析工具，直接讀取
`output/ai_report_YYYYMMDD.json`，並由前端 adapter 建立 view
model。原始 JSON schema 不需要修改。

## 資訊架構

1. 頂部狀態列：整體狀態、疲勞、體能、賽事準備度。
2. 每日決策摘要：`coaching_summary.headline`、三個洞察與三個行動。
3. 訓練負荷：`load_assessment` 的目前負荷、建議範圍與建議。
4. 4 週趨勢：週跑量折線與週訓練負荷長條，旁邊顯示每週 AI 解讀。
5. 心率區間：Z1-Z5 stacked bar 與區間明細。
6. 賽事準備度：信心分數與依 priority 排序的能力缺口。
7. 下週課表：固定 7 天 calendar，缺漏日期補恢復日。
8. 配速與生理能力：VO2max、乳酸閾值、心率、配速區間表。
9. 跑姿與經濟性：compact metrics、經濟性分數、改善建議。
10. AI 建議依據：`evidence_links` 可展開追溯層。

## 欄位對應

| 區塊 | JSON 欄位 |
|---|---|
| 頂部狀態列 | `athlete_status.overall_rating`, `athlete_status.fatigue_level`, `athlete_status.fitness_level`, `race_readiness.confidence_score` |
| 教練摘要 | `coaching_summary.headline`, `top_3_insights`, `top_3_actions` |
| 負荷狀態 | `load_assessment.current_tss_weekly`, `optimal_tss_range`, `status`, `label`, `recommendation` |
| 4 週趨勢 | `weekly_analysis[].sessions[]` derived metrics, `key_observation`, `weekly_assessment`, `weekly_recommendation`, `risk_flags` |
| 心率區間 | `hr_zone_distribution.zones`, `assessment`, `recommendation`, `is_polarized` |
| 生理能力 | `physio_metrics.vo2max`, `lactate_threshold`, `max_heart_rate`, `resting_heart_rate`, `pace_zones` |
| 賽事準備度 | `race_readiness.race_name`, `race_date`, `confidence_score`, `confidence_label`, `missing_capabilities` |
| 下週課表 | `next_week_plan.week_start`, `theme`, `days[]` |
| 跑姿與經濟性 | `running_mechanics.cadence_avg`, `ground_contact_ms`, `vertical_oscillation_cm`, `stride_length_m`, `running_economy_score`, `improvement_tips` |
| 依據層 | `evidence_links[].claim`, `supporting_metrics`, `supporting_sessions`, `source_path`, `confidence`, `visualization_hint` |

## 圖表類型

- 週跑量與訓練負荷：SVG combo chart，跑量折線、訓練負荷長條。
- 心率區間：Z1-Z5 stacked bar，並以小型區間卡顯示比例與分鐘數。
- 賽事準備度：conic score ring。
- 跑姿：compact metric cards。資料足夠時可再擴充 radar chart。
- 依據層：`metric_card`、`session_list`、`chart_annotation`、
  `calendar_badge`、`table_row` 先映射成 details 展開內容與小標籤。
  畫面上使用「指標卡」「活動列表」「圖表註記」等跑者可讀文字，
  raw hint 只保留在資料模型中。

## 空資料與錯誤狀態

- 找不到報告：顯示「找不到 output/ai_report_YYYYMMDD.json」。
- 週數不足：用現有週資料繪圖，不讓趨勢區空白。
- `sessions[]` 為空：該週 derived metrics 為 0，資料品質顯示「無訓練紀錄」。
- session 缺少 `distance_km`、`duration_min` 或 `training_load`：
  以 0 加總，該週資料品質顯示「部分資料不足」。
- `running_mechanics` 指標為 `null`：顯示「資料不足」。
- `pace_zones` 或 `hr_zone_distribution.zones` 缺漏：顯示空狀態或補 Z1-Z5 0 值。
- 配速區間若使用 `00:00` 表示開放端，畫面改顯示「快於 03:45/km」
  這類跑者語意，不直接顯示不可能的 `00:00` 配速。
- 舊報告沒有 `evidence_links`：顯示「此報告尚未提供可追溯依據」。

## Component Breakdown

- `ReportShell`：報告選擇、重整、載入狀態。
- `StatusGrid`：四張 score/status cards。
- `CoachSummaryPanel`：headline、insights、actions、依據按鈕。
- `LoadAssessmentPanel`：目前 weekly TSS、建議範圍、負荷建議。
- `WeeklyTrendPanel`：combo chart 與 weekly narrative stack。
- `HrZonePanel`：stacked bar、zone list、assessment/recommendation。
- `RaceReadinessPanel`：score ring、missing capability list。
- `NextWeekCalendar`：7 天課表與 key workout badge。
- `PhysioMetricsPanel`：生理指標 tiles 與 pace zone table。
- `RunningMechanicsPanel`：跑姿 metric cards 與 tips。
- `EvidenceLayer`：details accordion、metrics table、session table。

目前實作在 `dashboard/index.html`、`dashboard/styles.css`、
`dashboard/app.js` 與 `dashboard/reportAdapter.js`。

## Evidence Adapter 與 UI

`dashboard/reportAdapter.js` 的 `buildEvidence()` 會：

- 保留 `claim`、`supporting_metrics`、`supporting_sessions`、
  `source_sections`、`confidence`、`visualization_hint`。
- 用 `risk`、`fatigue`、`load`、`疲勞`、`風險`、`中暑` 等關鍵字
  將 high-risk claim 排在前面。
- 同風險層級內依 `confidence` 由高到低排序。
- 舊報告沒有 evidence 時建立 fallback message。
- `source_sections` 在 UI 轉成「近期訓練」「強度分佈」「課表建議」
  等可讀標籤，避免把 JSON key 直接攤給跑者。
- `supporting_sessions[].source_path` 會回查原始 `weekly_analysis`
  活動；若該活動有 `segments[]`，依據層會展開分段距離、配速、心率、
  步頻與備註，讓 interval 不只看整體平均值。

主畫面不攤 raw data。洞察與行動旁的「依據」按鈕會打開對應
`details`，展開後顯示關鍵數值、活動、`source_path` 與 confidence。

## Derived Weekly Metrics

前端 adapter 對每個 `weekly_analysis[]` 執行：

```text
derived_total_distance_km = sum(sessions[].distance_km || 0)，四捨五入 2 位
derived_total_duration_min = sum(sessions[].duration_min || 0)，四捨五入 1 位
derived_training_load = sum(sessions[].training_load || 0)，四捨五入 1 位
```

若任一 session 缺少或無法轉成數字，仍以 0 加總，並將該欄位加入
`missing_fields`。只要 `missing_fields` 非空，該週顯示「部分資料不足」。
即使舊報告包含週級 `total_distance_km`、`total_duration_min` 或
`training_load`，dashboard 也不讀取這些欄位。

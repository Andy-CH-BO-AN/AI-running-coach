# AI 跑步教練 Dashboard 設計與實作

這個 dashboard 是本機訓練分析工具，直接讀取
`output/ai_report_YYYYMMDD.json`，並由前端 adapter 建立 view
model。原始 JSON schema 不需要修改。

## 資訊架構（V2）

1. **Primary Action**：今日最優先行動（`coaching_summary.top_3_actions[0]`）。
2. **教練判斷 + 負荷 + 賽事**：warm 決策卡、7 日 TSS、賽事信心分數。
3. **最近訓練回顧**：依 `sessions[].type` 切換 easy / interval；interval 含 rep 折線。
4. **4 週 / 12 週趨勢**：跑量與負荷圖、週敘事、長期 sparkline。
5. **下週課表**：summary 列 + Key / Support；核心卡含配速、間歇距離、休息。
6. **Zone E**（`<details>` 預設收合）：心率區間、功率區間、配速區間表、跑姿。
7. **AI 建議依據**（預設收合）：claim → 數值表 → 分段明細；來源使用跑者可讀名稱，不直接露出 JSON path。

## 欄位對應

| 區塊 | JSON 欄位 |
|---|---|
| Primary Action | `coaching_summary.top_3_actions[0]`, `athlete_status.overall_rating` |
| 教練判斷 | `coaching_summary.headline`, `top_3_insights`, `top_3_actions` |
| 訓練負荷 | `load_assessment.current_tss_weekly`, `optimal_tss_range`, `status`, `label` |
| 賽事準備度 | `race_readiness.confidence_score`, `race_name`, `race_date` |
| 最近訓練 | `weekly_analysis[].sessions[]`（含 `segments[]`, `environment`） |
| 4 週趨勢 | `weekly_analysis[]` derived metrics, `weekly_assessment`, `risk_flags` |
| 12 週趨勢 | `twelve_week_summary`, `physio_metrics` |
| 下週課表 | `next_week_plan.theme`, `days[]`, `target_training_load` |
| 心率區間 | `hr_zone_distribution.zones`, `assessment`, `recommendation` |
| 功率區間 | `power_zone_distribution.zones`, `assessment`, `recommendation` |
| 配速區間 | `physio_metrics.pace_zones` |
| 跑姿 | `running_mechanics`（有效跑步分圈，排除休息段） |
| 依據層 | `evidence_links[].claim`, `supporting_metrics`, `supporting_sessions` |

## 圖表類型

- 週跑量與訓練負荷：SVG combo chart（跑量折線 + TSS 長條 + 4 週平均虛線）。
- 心率 / 功率區間：stacked bar + 區間比例列 + AI assessment / recommendation。
- Interval rep 趨勢：SVG 折線（X=rep, Y=pace）。
- 12 週：sparkline（跑量、訓練量；生理指標以數值卡呈現）。
- 配速區間：表格（zone、配速範圍、心率範圍）。

## 空資料與錯誤狀態

- 找不到報告：顯示載入失敗訊息。
- 週數不足：用現有週資料繪圖。
- `sessions[]` 為空：該週 derived metrics 為 0。
- 舊報告無 `power_zone_distribution`：功率區塊顯示「資料不足」；重跑 pipeline 後會有 zones + AI 解讀。
- 舊報告無 `evidence_links`：顯示 fallback 文案。
- 開發追蹤：adapter 保留 `source_path` 供程式除錯；dashboard 畫面顯示 human-readable `source_label`。

## Component Breakdown

- `ReportShell`：報告選擇（`YYYY/MM/DD（最新）`）、重整。
- `PrimaryActionBar`：今日指令 + 狀態 badge。
- `CoachSummaryPanel`：headline、教練觀察、下一步建議。
- `LoadAssessmentPanel` / `RaceReadinessPanel`：側欄數字卡。
- `LatestActivityPanel`：結論 + stat grid +（interval）rep 折線。
- `WeeklyTrendPanel` / `TwelveWeekPanel`：趨勢圖與敘事。
- `PlanSummaryBar` + `NextWeekCalendar`：主題、跑量、Key/Support 課表。
- `ZoneEPanel`：`<details>` 收合心率/功率/配速/跑姿。
- `EvidenceLayer`：metrics 表 + session 分段明細表（配速、心率、步頻、步幅）。

目前實作在 `dashboard/index.html`、`dashboard/styles.css`、
`dashboard/app.js` 與 `dashboard/reportAdapter.js`。

## Evidence Adapter 與 UI

`buildEvidence()` 會：

- 依 `source_path` 回查 `weekly_analysis[].sessions[]`，帶入完整 `segments[]`。
- 展開「查看依據數據」時，若有 segments，渲染分段明細表（含 warmup / main / recovery，並顯示步幅）。
- 主畫面只顯示跑者語言 claim；來源列顯示 human-readable `source_label`。

## Derived Weekly Metrics

```text
derived_total_distance_km = sum(sessions[].distance_km || 0)，四捨五入 2 位
derived_total_duration_min = sum(sessions[].duration_min || 0)，四捨五入 1 位
derived_training_load = sum(sessions[].training_load || 0)，四捨五入 1 位
```

前端不信任 AI 輸出的週級總量欄位，一律由 `sessions[]` 加總。

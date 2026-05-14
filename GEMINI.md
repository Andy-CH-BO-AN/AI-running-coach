# AI Agent Instructions: AI-running-coach

## 核心規則繼承 (Inheritance)

當你啟動此專案時，必須優先讀取並遵循以下路徑中的規範：

1. **開發工作流：** 參考 `ai/shared/` 下的指令，包含 Coding Workflow, Reviewer, QA 等。
2. **專案技能：** 參考 `ai/skills/` 下的 README review 指令。
3. **Prompt 範本：** 核心邏輯位於 `prompts/coach.md` 與 `prompts/goal.md`。

## 核心架構與職責邊界 (Crucial Design Principles)

- **職責分離：** 距離、日期、加總、百分比等「事實 (deterministic facts)」必須由 Python 程式端 (`coach_context.py`) 精確計算。**AI (Gemini) 僅負責教練語境的判讀、狀態標籤、風險解釋與課表安排，絕對不要讓 AI 進行精確數學計算。**
- **本地化：** 所有資料保留在本機，無需建構雲端服務架構。

## 專案架構脈絡

- **入口點：** `run_pipeline.py` (CLI 入口)
- **核心邏輯：** `src/pipeline/runner.py`
- **資料獲取：** `src/ingestion/garmin_client.py` (Garmin API 整合)
- **資料預處理：** `src/preprocessing/data_processor.py` (正規化) 與 `src/preprocessing/coach_context.py` (計算事實層)
- **AI 代理：** `src/agents/coach.py` (呼叫 Gemini 並解析 JSON)
- **前端展示：** `src/dashboard/server.py` 與 `dashboard/` (本機檢視介面)

## 技能要求 (Skills)

- 使用 Python 3.10+ 特性（如 memoryview, deques）。
- 熟悉 SQLAlchemy 2.0 與 Alembic 遷移，理解 Hybrid Schema 概念 (核心欄位用 SQL columns，Garmin 不固定指標用 JSONB)。
- 前端開發：Dashboard 為 **無 build step** 的 Vanilla HTML/JS/CSS，請勿引入 React/Vue 或 npm 構建工具。
- 測試框架：熟悉 `pytest` 撰寫單元測試與 DB 測試。
- 領域知識：理解長跑指標（心率區間 Z1-Z5、乳酸閾值、跑步動態如步頻與觸地時間等）。

## 指令行為

在執行任何建議前，請確認是否符合 `ai/shared/` 中的安全與質量規範。

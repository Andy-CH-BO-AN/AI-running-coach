# AI 跑步教練

AI 跑步教練是一個本機端 Garmin 到 AI 的訓練分析流程。它會從 Garmin Connect 抓取近期活動，整理活動指標，把結構化資料送給 Gemini，最後產生 Markdown 格式的訓練分析報告。

目前的教練提示詞聚焦在 1500m 目標、最近 1-2 週狀態、訓練負荷、心率區間、跑步動態，以及游泳等交叉訓練對跑步的影響。

## 功能

- 抓取 Garmin 個人資料、個人紀錄、近期活動、分圈資料，以及活動詳細 payload。
- 目前從 Garmin Connect 匯入 `running` 和 `lap_swimming` 活動。
- 在 preprocessing 階段整理跑步、游泳與自行車類型的指標；自行車資料處理能力已在 processor 中，但 Garmin 自行車活動匯入目前在 `src/ingestion/garmin_client.py` 中暫時關閉。
- 將 Garmin 原始活動與使用者資料儲存在 `data/raw/`。
- 將手動抓取的 raw API sample 儲存在 `data/sample/`，方便除錯與 QA。
- 將處理後的活動資料以 CSV 儲存在 `data/processed/`。
- 將最終 AI 教練分析報告以 Markdown 儲存在 `output/`。
- 將 AI agent 工作流規則集中在 shared Markdown，讓 GitHub Copilot、Codex，以及未來其他工具共用同一份 reviewer 與 QA 規則。

## 資料流程

```text
Garmin Connect
    ↓
src/ingestion/garmin_client.py
    ↓
src/preprocessing/data_processor.py
    ↓
src/agents/coach.py
    ↓
output/ai_report_YYYYMMDD.md
```

## 專案結構

- `run_pipeline.py`: CLI 入口，會把 `src/` 加進 `sys.path` 並執行 pipeline。
- `src/pipeline/runner.py`: 串接 Garmin 匯入、資料預處理、Gemini 分析與檔案輸出。
- `src/ingestion/garmin_client.py`: 處理 Garmin 登入、重試/backoff、profile/PR 抓取、活動詳細資料、分圈、心率區間與功率區間。
- `src/preprocessing/data_processor.py`: 計算配速/速度、格式化指標、整理進階活動資料，並產生效率摘要。
- `src/agents/coach.py`: 組合 Gemini prompt context，並支援本機分析報告輸出。
- `tool/save_raw_data.py`: 手動抓取 Garmin raw API sample，輸出到 `data/sample/`。
- `prompts/coach.md`: 主要教練提示詞。
- `prompts/goal.md`: 目前賽事目標與訓練限制。
- `data/raw/`: 本機 Garmin raw JSON 輸出，已被 git ignore。
- `data/processed/`: 本機 processed CSV 輸出，已被 git ignore。
- `data/sample/`: 本機 raw API sample，用於除錯，已被 git ignore。
- `output/`: 本機 Markdown 報告輸出，已被 git ignore。
- `ai/shared/`: AI workflow、reviewer、QA 的 canonical instructions。
- `.github/`: 指向 `ai/shared/` 的 GitHub Copilot adapters。
- `.codex/`: 指向 `ai/shared/` 的 Codex adapters。

## 安裝

1. 建立並啟用 Python virtual environment。

```bash
python -m venv .venv
source .venv/bin/activate
```

2. 安裝依賴。

```bash
pip install -r requirements.txt
```

3. 建立本機 `.env` 檔案。

```text
GARMIN_ACCOUNT=your_garmin_email
GARMIN_PASSWORD=your_garmin_password
GEMINI_KEY=your_gemini_api_key
```

## 執行

執行完整 Garmin 匯入與 AI 分析流程：

```bash
python run_pipeline.py
```

預期會產生以下本機輸出：

- `data/raw/garmin_raw_YYYYMMDD.json`
- `data/raw/garmin_user_YYYYMMDD.json`
- `data/processed/processed_YYYYMMDD.csv`
- `output/ai_report_YYYYMMDD.md`

Garmin 登入有時會需要手動驗證，也可能遇到 rate limit。程式已經有 retry/backoff，但除錯時仍建議避免反覆呼叫 Garmin API。

## 本機分析

如果想分析既有本機檔案、不重新抓 Garmin，可以使用 `src/agents/coach.py` 裡的 `run_local_analysis`，傳入 processed CSV、raw user JSON，以及可選的 goal prompt。

範例：

```bash
python src/agents/coach.py
```

`__main__` block 裡的檔名是範例，使用前請先改成你本機實際存在的檔案。

如果想額外抓一份 raw API sample 來除錯，可以執行：

```bash
python tool/save_raw_data.py
```

## 測試

執行自動化 unit tests：

```bash
python3 -m pytest -q \
  tests/test_data_processor.py \
  tests/test_qa_data_processor.py \
  tests/test_garmin_client_details.py \
  tests/test_runner.py \
  tests/test_coach.py
```

目前已追蹤的測試包含：

- `tests/test_data_processor.py`: 測試 preprocessing 的活動型別分流、效率指標、配速格式化，以及短距離自行車過濾邏輯。
- `tests/test_qa_data_processor.py`: 補強 preprocessing 的邊界值、效率欄位回歸，以及 fast swimmer / partial None 這類 QA 案例。
- `tests/test_garmin_client_details.py`: 測試 Garmin 活動詳細資料解析、巢狀指標擷取，以及 time-in-zone fallback payload。
- `tests/test_runner.py`: 測試 pipeline 在 preprocessing 全數過濾時仍會保留 raw/user artifact，並驗證 processed CSV 與 Markdown report 的輸出流程。
- `tests/test_coach.py`: 測試教練 prompt context 組裝，以及本機分析模式會讀取 user JSON 並寫出 Markdown report。
- `tests/scripts/garmin_client_smoke.py`: 手動 Garmin smoke test，會呼叫真實 Garmin API，且需要本機 credentials。

`pytest -q` 可能會收集到 repo root 的本機/手動測試腳本。自動化測試建議使用上方明確指令，手動 Garmin smoke test 請用：

```bash
python tests/scripts/garmin_client_smoke.py
```

## AI Agent 工作流

這個 repo 使用 shared Markdown 作為 AI coding workflow instructions 的單一來源。

Canonical docs:

- `ai/shared/instructions.md`
- `ai/shared/reviewer.agent.md`
- `ai/shared/qa.agent.md`

Adapters:

- `.github/copilot-instructions.md`
- `.github/agents/reviewer.agent.md`
- `.github/agents/qa.agent.md`
- `.codex/copilot-instructions.md`
- `.codex/agents/reviewer.agent.md`
- `.codex/agents/qa.agent.md`

未來如果要加入 Claude、Gemini 或其他工具，只需要建立指向 `ai/shared/` 的薄 adapter，不要重複撰寫 reviewer 或 QA 規則。

## 注意事項

- `.env`、`data/`、`output/`、`.venv/` 和 CSV 檔案都已被 git ignore。
- 主要最終報告是 Markdown，不是 CSV；CSV 是處理後資料備份。
- 有些 Garmin 進階指標取決於裝置支援，舊活動可能沒有完整資料。
- 設定 `GARMIN_DEBUG_ACTIVITY_DETAILS=1` 可以啟用 `garmin_client.py` 的活動 payload 除錯輸出。

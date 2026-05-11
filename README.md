# AI 跑步教練

AI 跑步教練會從 Garmin Connect 抓取你最近的訓練資料，整理成
結構化指標，並產出一份 Markdown 格式的 AI 訓練分析報告。

目前分析重點聚焦在 1500m 目標、最近 1-2 週狀態、訓練負荷、
心率區間、跑步動態，以及游泳等交叉訓練對跑步的影響。

這個專案目前是本機端 workflow，不是雲端服務。它適合想保留
Garmin 原始資料、自己掌握分析流程、並快速產出訓練回顧的跑者。

## 目前能做什麼

- 從 Garmin Connect 抓取個人資料、個人紀錄、近期活動、分圈資
  料，以及活動詳細 payload。
- 目前支援匯入 `running` 和 `lap_swimming` 活動。
- 整理跑步、游泳與自行車類型的指標，並輸出 processed CSV。
- 產出 Markdown 格式的 AI 訓練分析報告。
- 將 Garmin raw JSON、使用者資料與 processed artifact 存在本
  機，方便除錯、重跑與 QA。
- 可選擇匯入 PostgreSQL，支援長期趨勢分析與後續 feature
  engineering。
- 將 AI workflow、reviewer、QA、安全規則集中在 shared
  Markdown，讓 GitHub Copilot、Codex 與其他工具共用同一份
  canonical instructions。

## 目前限制

- 這是本機端流程，不是多使用者產品，也沒有 web UI。
- Garmin 活動匯入有 `running` 、 `lap_swimming`以及自行車。
- Garmin 登入有時需要手動驗證，也可能遇到 rate limit。
- PostgreSQL 是選用的進階模式；只想跑 Garmin 匯入與 AI 分析
  時，不需要 DB。

## 3 分鐘快速開始

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
GARMIN_PASSWORD=
GEMINI_KEY=your_gemini_api_key
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach
TEST_DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach_test
```

請在本機 `.env` 填入 `GARMIN_PASSWORD` 與 `GEMINI_KEY`。如果你
要使用選用的 PostgreSQL 匯入流程，再補上 `POSTGRES_PASSWORD`、
`DATABASE_URL` 與 `TEST_DATABASE_URL`。`POSTGRES_PASSWORD`
不放進 git tracked files，避免 secret scanner 將範例密碼當成憑
證。

4. 執行完整 Garmin 匯入與 AI 分析流程。

```bash
python run_pipeline.py
```

## 執行後會得到什麼

正常情況下，主流程會在本機產生：

- `data/raw/garmin_raw_YYYYMMDD.json`
- `data/raw/garmin_user_YYYYMMDD.json`
- `data/processed/processed_YYYYMMDD.csv`
- `output/ai_report_YYYYMMDD.md`

其中 Markdown 報告是主要成果物；CSV 則是處理後資料備份，方便
除錯、QA、以及後續分析。

Garmin 登入有時會需要手動驗證，也可能遇到 rate limit。程式已
經有 retry/backoff，但除錯時仍建議避免反覆呼叫 Garmin API。

## 本機分析

如果想分析既有本機檔案、不重新抓 Garmin，可以使用
`src/agents/coach.py` 裡的 `run_local_analysis`，傳入 processed
CSV、raw user JSON，以及可選的 goal prompt。

範例：

```bash
python src/agents/coach.py
```

`__main__` block 裡的檔名是範例，使用前請先改成你本機實際存在
的檔案。

如果想額外抓一份 raw API sample 來除錯，可以執行：

```bash
python tool/save_raw_data.py
```

## 進階：匯入 PostgreSQL（選用）

如果你只是想跑 Garmin 匯入與 AI 分析，可以直接跳過這一節。
`python run_pipeline.py` 不需要 PostgreSQL。

如果你有開啟 PostgreSQL，`python run_pipeline.py` 會優先使用 DB：
先查 PostgreSQL 裡最近最新那天的活動，再向 Garmin 補抓該日期
之後（含同日）的 `running`、`lap_swimming`、`cycling` 活動，
靠 `garmin_activity_id` upsert 避免重複，最後固定從 DB 載入最
近 75 筆活動送給 AI coach。若本機 DB 暫時無法連線，pipeline
仍會 fallback 成直接從 Garmin 抓最近 75 筆並輸出 Markdown。

這個 DB layer 也提供另一條本機匯入路徑，可以把既有
`data/raw/` 與 `data/processed/` artifact 寫入 PostgreSQL，
方便後續做長期趨勢分析、weekly summary、fatigue tracking、
feature engineering versioning 與 AI report evaluation。

啟動本機 PostgreSQL：

```bash
docker compose up -d postgres
```

執行 migration：

```bash
alembic upgrade head
```

匯入本機 Garmin 檔案：

```bash
python -m src.scripts.import_garmin_files \
  --user-file data/raw/garmin_user_20260510.json \
  --raw-file data/raw/garmin_raw_20260510.json \
  --processed-file data/processed/processed_20260510.csv
```

如果要補大量歷史資料，建議先 raw-only fetch，不跑 preprocessing
與 AI coach：

```bash
python -m src.scripts.fetch_garmin_raw --limit 999 --import-db
```

這會寫出新的 `data/raw/garmin_user_YYYYMMDD.json` 與
`data/raw/garmin_raw_YYYYMMDD.json`，並在 `--import-db` 開啟
時直接匯入 PostgreSQL。若只想先抓檔案、晚點再匯入，可以省略
`--import-db`，再用 `src.scripts.import_garmin_files` 匯入。

Garmin login API 很容易先顯示兩次 `429` rate limit 訊息，之後
才繼續做事。raw-only fetch 已加上 progress log；看到兩次
`429` 後請先等 3-8 分鐘再判斷是否真的卡住，避免一直重跑造成
Garmin 更嚴格限流。

`--processed-file` 是 optional。`garmin_raw_YYYYMMDD.json` 是
activity、splits、swimming lengths 的 source of truth；
`garmin_user_YYYYMMDD.json` 會寫入 `user_profile_snapshots`，
同日匯入會 upsert，同一使用者不同日期會保留歷史，例如
VO2max、resting HR、threshold pace、體重變化。

目前 schema 使用 hybrid design：

- 穩定且常查詢的欄位放 SQL columns，例如 `distance_km`、
  `duration_min`、`average_pace_min_per_km`、`average_speed_kmh`、
  `average_heart_rate`、`training_stress_score`。
- Garmin 可能變動或不固定的 metrics 放 JSONB，例如
  `raw_metrics`、split `metrics`、`raw_profile`。
- 完整 raw payload 會保留在 `activities.raw_json` 與
  `user_profile_snapshots.raw_profile`，之後 feature engineering
  可以重跑。

DB 測試需要 PostgreSQL test database，不會呼叫 Garmin API。設
定 `TEST_DATABASE_URL` 後執行：

```bash
docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" ai_running_coach_test || true'

python3 -m pytest -q tests/test_db_importer.py tests/test_db_repositories.py
```

如果沒有 test database，DB tests 會 skip；一般 pipeline unit
tests 不受影響。DB tests 也會拒絕 `TEST_DATABASE_URL` 等於
`DATABASE_URL` 或 database 名稱不含 `test` 的連線，並只在
temporary schema 內建表，避免誤清本機主 DB。

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

- `run_pipeline.py`: CLI 入口，會把 `src/` 加進 `sys.path` 並執
  行 pipeline。
- `src/pipeline/runner.py`: 串接 Garmin 匯入、資料預處理、
  Gemini 分析與檔案輸出。
- `src/ingestion/garmin_client.py`: 處理 Garmin 登入、
  重試/backoff、profile/PR 抓取、活動詳細資料、分圈、心率區
  間與功率區間。
- `src/preprocessing/data_processor.py`: 計算配速/速度、格式化指
  標、整理進階活動資料，並產生效率摘要。
- `src/agents/coach.py`: 組合 Gemini prompt context，並支援本
  機分析報告輸出。
- `src/db/`: SQLAlchemy 2.0 models、DB session 與 repository
  layer。
- `src/services/db_importer.py`: 將本機 Garmin raw/user/processed
  檔案匯入 PostgreSQL。
- `src/services/feature_persistence.py`: activity feature persistence
  placeholder，供後續 feature engineering 版本化使用。
- `src/scripts/import_garmin_files.py`: 選用的 DB import CLI。
- `src/scripts/fetch_garmin_raw.py`: raw-only Garmin fetch CLI，可抓
  大量歷史活動但不跑 AI coach。
- `alembic/`: PostgreSQL schema migration。
- `tool/save_raw_data.py`: 手動抓取 Garmin raw API sample，輸出
  到 `data/sample/`。
- `prompts/coach.md`: 主要教練提示詞。
- `prompts/goal.md`: 目前賽事目標與訓練限制。
- `data/raw/`: 本機 Garmin raw JSON 輸出，已被 git ignore。
- `data/processed/`: 本機 processed CSV 輸出，已被 git ignore。
- `data/sample/`: 本機 raw API sample，用於除錯，已被 git ignore。
- `output/`: 本機 Markdown 報告輸出，已被 git ignore。
- `ai/shared/`: AI workflow、reviewer、QA 的 canonical
  instructions。
- `.github/`: 指向 `ai/shared/` 與 `ai/skills/` 的 GitHub Copilot
  adapters。
- `.codex/`: 指向 `ai/shared/` 與 `ai/skills/` 的 Codex adapters。

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

- `tests/test_data_processor.py`: 測試 preprocessing 的活動型別分流、
  效率指標、配速格式化，以及短距離自行車過濾邏輯。
- `tests/test_qa_data_processor.py`: 補強 preprocessing 的邊界值、
  效率欄位回歸，以及 fast swimmer / partial None 這類 QA 案例。
- `tests/test_garmin_client_details.py`: 測試 Garmin 活動詳細資料解
  析、巢狀指標擷取，以及 time-in-zone fallback payload。
- `tests/test_runner.py`: 測試 pipeline 在 preprocessing 全數過濾
  時仍會保留 raw/user artifact，並驗證 processed CSV 與
  Markdown report 的輸出流程。
- `tests/test_coach.py`: 測試教練 prompt context 組裝，以及本機
  分析模式會讀取 user JSON 並寫出 Markdown report。
- `tests/test_db_importer.py`: 測試 Garmin local files 匯入
  PostgreSQL 的 idempotency 與 raw payload preservation。
- `tests/test_db_repositories.py`: 測試 repository upsert、profile
  history、feature versions、AI report versions。
- `tests/test_fetch_garmin_raw.py`: 測試 raw-only fetch CLI 寫出
  Garmin raw/user JSON，不呼叫真實 Garmin API。
- `tests/scripts/garmin_client_smoke.py`: 手動 Garmin smoke test，
  會呼叫真實 Garmin API，且需要本機 credentials。

`pytest -q` 可能會收集到 repo root 的本機/手動測試腳本。自動
化測試建議使用上方明確指令，手動 Garmin smoke test 請保守使
用：

```bash
python tests/scripts/garmin_client_smoke.py
```

## AI Agent 工作流

這個 repo 使用 shared Markdown 作為 AI coding workflow
instructions 的單一來源。

Canonical docs:

- `ai/shared/instructions.md`
- `ai/shared/reviewer.agent.md`
- `ai/shared/qa.agent.md`
- `ai/shared/security.agent.md`
- `ai/skills/python-review-qa-loop/SKILL.md`
- `ai/skills/readme-pm-review/SKILL.md`

Adapters:

- `.github/copilot-instructions.md`
- `.github/agents/reviewer.agent.md`
- `.github/agents/qa.agent.md`
- `.github/agents/security.agent.md`
- `.github/skills/python-review-qa-loop/SKILL.md`
- `.github/skills/readme-pm-review/SKILL.md`
- `.codex/copilot-instructions.md`
- `.codex/agents/reviewer.agent.md`
- `.codex/agents/qa.agent.md`
- `.codex/agents/security.agent.md`
- `.codex/skills/python-review-qa-loop/SKILL.md`
- `.codex/skills/readme-pm-review/SKILL.md`

未來如果要加入 Claude、Gemini 或其他工具，只需要建立指向
`ai/shared/` 與 `ai/skills/` 的薄 adapter，不要重複維護 workflow
規則。

## 注意事項

- `.env`、`data/`、`output/`、`.venv/` 和 CSV 檔案都已被
  git ignore。
- 主要最終報告是 Markdown，不是 CSV；CSV 是處理後資料備份。
- 有些 Garmin 進階指標取決於裝置支援，舊活動可能沒有完整資料。
- 設定 `GARMIN_DEBUG_ACTIVITY_DETAILS=1` 可以啟用
  `garmin_client.py` 的活動 payload 除錯輸出。

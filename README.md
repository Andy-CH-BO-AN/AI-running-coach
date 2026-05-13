# AI 跑步教練

AI 跑步教練會從 Garmin Connect 抓取你最近的訓練資料，整理成
結構化指標，並產出一份 JSON 格式的 AI 訓練分析報告。

目前分析重點聚焦在 1500m 目標、最近 1-2 週狀態、訓練負荷、
心率區間、跑步動態，以及游泳等交叉訓練對跑步的影響。

這個專案目前是本機端 workflow，不是雲端服務。它適合想保留
Garmin 原始資料、自己掌握分析流程、並快速產出訓練回顧的跑者。

## 目前能做什麼

- 從 Garmin Connect 抓取個人資料、個人紀錄、近期活動、分圈資
  料，以及活動詳細 payload。
- 目前支援匯入 `running` 和 `lap_swimming` 活動。
- 整理跑步、游泳與自行車類型的指標，並輸出 processed CSV。
- 產出 JSON 格式的 AI 訓練分析報告。
- 以本機 dashboard 讀取 `output/ai_report_YYYYMMDD.json`，快速檢視
  訓練狀態、週負荷、心率區間、賽事準備度與下週課表。
- 將 Garmin raw JSON、使用者資料與 processed artifact 存在本
  機，方便除錯、重跑與 QA。
- 可選擇匯入 PostgreSQL，支援長期趨勢分析與後續 feature
  engineering。
- 將 AI workflow、reviewer、QA、安全規則集中在 shared
  Markdown，讓 GitHub Copilot、Codex 與其他工具共用同一份
  canonical instructions。

## 目前限制

- 這是本機端流程，不是多使用者產品；dashboard 只在本機讀取已
  產生的 JSON 報告。
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

如果想先確認可用參數：

```bash
python run_pipeline.py --help
```

### 自訂賽事目標與訓練偏好

`prompts/goal.md` 是預設目標與訓練限制。直接執行
`python run_pipeline.py` 時會使用這份預設內容；如果執行時傳入
參數，只有被指定的區塊會被暫時覆蓋，原本的 `prompts/goal.md`
不會被改寫。

常用參數：

- `--activity-limit`: AI coach 最後要分析幾筆近期活動，預設 75。
- `--fetch-limit`: 同步 Garmin 時最多往前抓幾筆活動。預設跟
  `--activity-limit` 相同；如果要補大量歷史資料，可以明確傳
  `--fetch-limit 999` 或使用 raw-only fetch。
- `--core-goal`: 你的賽事距離、比賽日期、目標成績，以及目前訓
  練重點。會覆蓋 `prompts/goal.md` 的「核心目標」區塊。
- `--core-goal-file`: 從 markdown/text 檔讀取核心目標；內容較長
  時比在命令列直接輸入更方便。
- `--training-preferences`: 你一週練幾次、休息幾天、是否有其他
  運動、傷痛史、不能安排強度課的日期等。會覆蓋
  `prompts/goal.md` 的「訓練偏好與限制」區塊。
- `--training-preferences-file`: 從 markdown/text 檔讀取訓練偏
  好與限制；適合多人或多目標輪流分析。

範例：只改賽事目標，訓練偏好沿用 `prompts/goal.md`。

```bash
python run_pipeline.py \
  --core-goal "賽事名稱：城市路跑；賽事距離：10K；賽事日期：2026-11-08；目標成績：45:00"
```

範例：同時覆蓋目標與訓練偏好。

```bash
python run_pipeline.py \
  --core-goal "半馬，2026-12-13，目標 1:45，現在重點是穩定有氧與長跑" \
  --training-preferences "每週跑 4 天、休息 2 天、週三游泳、週五重訓，避免重訓隔天排跑步強度"
```

範例：內容較長時，先寫成檔案再傳入。

```bash
python run_pipeline.py \
  --core-goal-file prompts/examples/half_marathon_goal.md \
  --training-preferences-file prompts/examples/weekly_constraints.md
```

## 執行後會得到什麼

正常情況下，主流程會在本機產生：

- `data/raw/garmin_raw_YYYYMMDD.json`
- `data/raw/garmin_user_YYYYMMDD.json`
- `data/processed/processed_YYYYMMDD.csv`
- `data/processed/coach_context_YYYYMMDD.json`
- `output/ai_report_YYYYMMDD.json`

其中 JSON 報告是 dashboard 的資料來源；CSV 則是處理後活動資
料備份。`coach_context_YYYYMMDD.json` 是送給 Gemini 前由本機
程式端 deterministic 計算好的教練上下文，方便除錯、QA、以及
後續分析。

### 程式端先算好的資料

pipeline 會先從 raw/user/processed 資料建立
`data/processed/coach_context_YYYYMMDD.json`，再把它交給 Gemini。
這些欄位不依賴 Gemini 判斷：

- 近 4 週 Monday-based week bucket、每週 sessions 清單、週總距
  離、週總時間、週訓練負荷與資料品質狀態。
- 每次活動的距離、時間、training load、平均心率、平均配速、
  aerobic/anaerobic training effect、分圈 segments 與高溫環境
  seed。
- 4 週心率 Z1-Z5 minutes/percentage，以及是否偏極化的 seed。
- VO2max、最大/靜息心率、乳酸閾值心率/配速與 pace zone seed。
- 跑姿平均值：cadence、ground contact、vertical oscillation、
  stride length 與 running economy score seed。若有分圈資料，會
  優先使用有效跑步分圈並排除間歇休息/走動段，避免步頻與步幅被
  低強度恢復段拉低。
- swimming/cycling 交叉訓練摘要、目前 weekly TSS load seed、下
  週 7 天日期與可訓練日/長跑偏好。
- 可被 Gemini 寫入 `evidence_links` 的 deterministic facts，例
  如本週負荷、Z4-Z5 佔比與風險 flag。

Gemini 主要負責把這些事實轉成教練判讀：狀態標籤、風險解釋、
賽事準備度、下週訓練安排、週期化與可追溯 evidence 文案。日期、
加總與百分比這類 deterministic numbers 由本機程式端負責。

### 開啟本機 Dashboard

完成 `python run_pipeline.py` 並產生 `output/ai_report_YYYYMMDD.json`
後，可以啟動本機 dashboard：

```bash
python3 -m src.dashboard.server
```

預設網址是 `http://127.0.0.1:8765`。畫面會掃描 `output/` 中的
JSON 報告，並優先載入日期最新的一份。設計與欄位對應細節見
[`docs/dashboard.md`](docs/dashboard.md)。

Dashboard 會把 JSON 欄位名稱轉成跑者可讀標籤，例如「近期訓練」、
「強度分佈」與「課表建議」，避免直接顯示 raw schema key。AI
建議依據層會保留可追溯來源，並在 interval 活動下展開分段距離、
配速、心率與步頻；配速區間若有開放端，例如 Z5 的 `00:00`，畫
面會顯示成「快於 03:45/km」這類跑者語意。

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
仍會 fallback 成直接從 Garmin 抓最近 75 筆並輸出 JSON。

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
src/preprocessing/coach_context.py
    ↓
src/agents/coach.py
    ↓
output/ai_report_YYYYMMDD.json
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
- `src/preprocessing/coach_context.py`: 從 processed/raw/user 資
  料建立 deterministic coach context，包含週級 derived metrics、
  心率區間、跑姿、生理 profile seed 與下週日期 seed。
- `src/agents/coach.py`: 組合 Gemini prompt context，並支援本
  機分析報告輸出。
- `src/dashboard/server.py`: 服務本機 dashboard 與
  `output/ai_report_YYYYMMDD.json` read-only API。
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
- `output/`: 本機 AI JSON 報告輸出，已被 git ignore。
- `dashboard/`: 無 build 的本機訓練狀態 dashboard 前端。
- `docs/dashboard.md`: dashboard 資訊架構、欄位對應與 adapter
  規則。
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
  tests/test_coach.py \
  tests/test_coach_context.py \
  tests/test_dashboard_adapter.py \
  tests/test_dashboard_server.py
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
  JSON report 的輸出流程。
- `tests/test_coach.py`: 測試教練 prompt context 組裝，以及本機
  分析模式會讀取 user JSON 並寫出 JSON report。
- `tests/test_coach_context.py`: 測試 deterministic coach context
  的週一 bucket、derived weekly metrics、缺資料標示、心率區間
  百分比、Z5 開放端配速 seed，以及下週日期/可訓練日 seed。
- `tests/test_dashboard_adapter.py`: 測試 dashboard adapter 的週級
  derived metrics、課表日期修正、依據連結、中文標籤、風險標籤、
  interval 分段展開，以及開放端配速顯示。
- `tests/test_dashboard_server.py`: 測試本機 dashboard report API
  的報告掃描、檔名防護與 JSON 物件讀取。
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
- 主要最終報告是 JSON，不是 CSV；CSV 是處理後資料備份。
- 有些 Garmin 進階指標取決於裝置支援，舊活動可能沒有完整資料。
- 設定 `GARMIN_DEBUG_ACTIVITY_DETAILS=1` 可以啟用
  `garmin_client.py` 的活動 payload 除錯輸出。

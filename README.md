# AI 跑步教練

本機端 Garmin 訓練分析 workflow：同步近期 Garmin Connect 活動，先用
Python 產生可追溯的訓練指標，再交給 Gemini 產出 JSON 教練報告，最後用
本機 dashboard 檢視訓練狀態、風險、賽事準備度與下週課表。

這不是雲端服務，也不是多使用者產品。Garmin raw data、processed
artifacts、coach context 與 AI report 都留在本機，適合想保留資料控制權、
又想把訓練紀錄轉成教練語意的個人跑者。

## 適合誰

- 想把 Garmin 原始資料留在本機，並能重跑、除錯、QA 的跑者。
- 想快速看懂近 1-4 週訓練負荷、心率區間、跑姿與交叉訓練意義的人。
- 想用 AI 輔助週訓練安排，但希望距離、日期、加總與百分比先由程式端 deterministic 計算的人。
- 想逐步累積 PostgreSQL 訓練資料，未來做長期趨勢、feature engineering 或 report evaluation 的開發者。

## 目前能做什麼

- 從 Garmin Connect 抓取個人資料、個人紀錄、近期活動、分圈資料與活動詳細 payload。
- 支援 `running`、`lap_swimming`、`cycling`，並分開計算各運動週距離與負荷。
- 產生 processed CSV、deterministic coach context JSON，以及 AI coach JSON report。
- 在程式端計算週訓練負荷、分運動週量、心率/功率 Z1-Z5、跑姿、配速/心率區間、交叉訓練摘要與下週日期 seed。
- 透過 Gemini 把 deterministic facts 轉成狀態標籤、風險解釋、賽事準備度、下週課表、強度解讀與 evidence 文案。
- 啟動本機 dashboard，讀取 `output/ai_report_YYYYMMDD.json`，呈現訓練回顧、週期化脈絡、下週課表、四週訓練卡、交叉訓練分析與 Zone E。
- 選用 PostgreSQL 匯入 raw/user/processed artifacts，支援 idempotent upsert 與後續資料版本化。

## 目前限制

- Garmin 登入有時需要手動驗證，也可能遇到 rate limit；程式有 retry/backoff，但除錯時仍建議避免反覆呼叫 API。
- Dashboard 只讀本機已產生的 report，不會主動同步 Garmin 或修改資料。
- PostgreSQL 是選用進階模式；只想同步 Garmin 並產生 AI 報告時可以不啟動 DB。
- 有些 Garmin 進階指標取決於裝置與活動類型，舊活動可能沒有完整心率區間、功率、跑姿或游泳 lengths。

## 快速開始

### 1. 建立 Python 環境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. 建立 `.env`

```bash
cp .env.example .env
```

最小必要設定：

```text
GARMIN_ACCOUNT=your_garmin_email
GARMIN_PASSWORD=your_garmin_password
GOOGLE_API_KEY=your_gcp_api_key
GOOGLE_GENAI_USE_VERTEXAI=true
```

`GOOGLE_API_KEY` 會優先於舊的 `GEMINI_KEY`。使用 GCP / Vertex AI API key
時，建議設定 `GOOGLE_GENAI_USE_VERTEXAI=true`；如果改用 ADC / OAuth2
憑證而非 API key，再設定 `GOOGLE_CLOUD_PROJECT` 與
`GOOGLE_CLOUD_LOCATION`。

PostgreSQL 只有在要匯入 DB、跑 migration 或 DB tests 時才需要：

```text
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_local_postgres_password
DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach
TEST_DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach_test
```

### 3. 跑主流程

```bash
python run_pipeline.py
```

主流程會同步 Garmin、預處理資料、建立 deterministic coach context、
呼叫 Gemini，並輸出 JSON report。可用 `--help` 查看參數：

```bash
python run_pipeline.py --help
```

### 4. 開本機 Dashboard

完成主流程並產生 `output/ai_report_YYYYMMDD.json` 後：

```bash
python3 -m src.dashboard.server
```

預設網址是 `http://127.0.0.1:8765`。Dashboard 會掃描 `output/`，
優先載入日期最新的 report（選單顯示 `2026/05/16（最新）` 格式）。
設計與欄位對應見 [`docs/dashboard.md`](docs/dashboard.md)。

## 你會得到什麼

主流程會在本機產生以下檔案：

| 檔案 | 用途 |
| --- | --- |
| `data/raw/garmin_raw_YYYYMMDD.json` | Garmin activities raw payload，包含活動、分圈與游泳 lengths。 |
| `data/raw/garmin_user_YYYYMMDD.json` | 使用者 profile、PR、生理資料與訓練日偏好。 |
| `data/processed/processed_YYYYMMDD.csv` | 經 preprocessing 正規化後的活動資料備份。 |
| `data/processed/coach_context_YYYYMMDD.json` | 程式端 deterministic coach context，是送給 Gemini 前的事實層。 |
| `output/ai_report_YYYYMMDD.json` | AI coach 最終 JSON report，也是 dashboard 的資料來源。 |

`coach_context_YYYYMMDD.json` 由本機程式先計算：

- 近 4 週 Monday-based week bucket、sessions、分運動週距離、週總時間、訓練負荷與資料品質。
- 每次活動的距離、時間、training load、平均心率、平均配速、training effect、segments 與高溫 seed。
- 4 週心率 Z1-Z5 minutes/percentage，以及是否偏極化的 seed。
- VO2max、最大/靜息心率、乳酸閾值心率/配速、pace zone seed 與以儲備心率推估的心率區間。
- 跑姿平均值：cadence、ground contact、vertical oscillation、stride length 與 running economy score seed。
- 游泳/自行車交叉訓練摘要、每週高負荷交叉訓練候選、weekly TSS load seed、下週 7 天日期與可訓練日/長跑偏好。
- 可被 Gemini 寫入 `evidence_links` 的 deterministic facts，例如本週負荷、Z4-Z5 佔比與風險 flag。

Gemini 主要負責教練判讀與文字化；日期、加總、百分比與可追溯 facts
由本機程式端負責。

## Dashboard 重點

- **訓練計畫**：顯示 AI `periodization` 的目前階段、距離目標賽週數、階段週結構，並接續呈現下週核心/輔助課表。
- **訓練回顧**：優先選最近一次 interval / tempo / long / race 等重點訓練；沒有重點課時回退到最新活動。
- **強度分佈**：心率與功率區間並列，含 AI `assessment` / `recommendation`（需重跑 pipeline 產生新 report）。
- **四週回顧**：週卡以 2x2 排列，分開顯示跑步、游泳、自行車距離，並由 AI 每週挑出代表強度課與一堂高負荷交叉訓練。
- **Zone E**：預設收合的 `<details>`，內含配速區間表與跑姿（排除休息段的有效跑步分圈）。
- **Evidence**：展開後顯示 supporting session 的分段明細，包含配速、心率、步頻與步幅；畫面使用跑者可讀來源名稱，不直接露出 JSON path。

### 5. 用 Docker 跑 Dashboard

如果你想直接用容器啟動 dashboard 與 PostgreSQL：

```bash
docker compose up -d postgres dashboard
```

這個 compose 設定會：

- 讓 `dashboard` service 讀取本機 `output/`，直接顯示最新的 `output/ai_report_YYYYMMDD.json`
- 把 `POSTGRES_HOST` / `POSTGRES_*` 傳進容器，由 app 用 SQLAlchemy 安全組出 `DATABASE_URL`
- 使用 `.env` 裡的 `POSTGRES_USER` / `POSTGRES_PASSWORD`
- 避免密碼含 `@`、`:` 這類字元時把 PostgreSQL URI 拼壞

常用指令：

```bash
docker compose build dashboard
docker compose down
```

預設 dashboard 網址仍是 `http://127.0.0.1:8765`。

## 自訂賽事目標

預設訓練目標與限制放在 `prompts/goal.md`。直接執行
`python run_pipeline.py` 會使用這份檔案；如果透過 CLI 傳入目標或訓練
偏好，只會暫時覆蓋 prompt context，不會改寫 `prompts/goal.md`。

常用參數：

- `--activity-limit`: AI coach 最後分析幾筆近期活動，預設 75。
- `--fetch-limit`: 同步 Garmin 時最多往前抓幾筆活動；未指定時等於 `--activity-limit`。
- `--core-goal`: 賽事距離、日期、目標成績與目前訓練重點。
- `--core-goal-file`: 從 markdown/text 檔讀取核心目標。
- `--training-preferences`: 每週訓練頻率、休息日、交叉訓練、傷痛史與排課限制。
- `--training-preferences-file`: 從 markdown/text 檔讀取訓練偏好與限制。

範例：

```bash
python run_pipeline.py \
  --core-goal "半馬，2026-12-13，目標 1:45，現在重點是穩定有氧與長跑" \
  --training-preferences "每週跑 4 天、休息 2 天、週三游泳、週五重訓，避免重訓隔天排跑步強度"
```

如果內容較長，可以先寫成本機檔案：

```bash
python run_pipeline.py \
  --core-goal-file my_goal.md \
  --training-preferences-file my_training_limits.md
```

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
    ↓
dashboard/
```

## 本機分析與 raw-only fetch

如果想分析既有本機檔案、不重新抓 Garmin，可以使用
`src/agents/coach.py` 裡的 `run_local_analysis`。`__main__` block
內的檔名只是範例，使用前請改成你本機實際存在的 processed CSV 與
user JSON。

```bash
python src/agents/coach.py
```

如果想先抓大量 raw Garmin 檔案、不跑 preprocessing 與 AI coach：

```bash
python -m src.scripts.fetch_garmin_raw --limit 999
```

若要抓完後直接匯入 PostgreSQL：

```bash
python -m src.scripts.fetch_garmin_raw --limit 999 --import-db
```

Garmin login API 很容易先顯示兩次 `429` rate limit 訊息，之後才繼續
做事。看到 `429` 後請先等 3-8 分鐘再判斷是否真的卡住，避免一直重跑
造成更嚴格限流。

## 進階：PostgreSQL（選用）

`python run_pipeline.py` 會優先嘗試 DB mode：先查 PostgreSQL 中最新
活動日期，再向 Garmin 補抓該日期之後的 `running`、`lap_swimming`、
`cycling` 活動，靠 `garmin_activity_id` upsert 避免重複。user profile
匯入時也會保存每日靜止心率；同一天已有資料時採較低值，coach context
會取最近一筆可用靜止心率。若 DB 無法連線，pipeline 會 fallback 成直接
從 Garmin 抓近期活動並輸出檔案。

啟動本機 PostgreSQL：

```bash
docker compose up -d postgres
```

執行 migration：

```bash
alembic upgrade head
```

匯入既有本機 Garmin artifacts：

```bash
python -m src.scripts.import_garmin_files \
  --user-file data/raw/garmin_user_20260510.json \
  --raw-file data/raw/garmin_raw_20260510.json \
  --processed-file data/processed/processed_20260510.csv
```

目前 DB schema 採 hybrid design：

- 穩定且常查詢的欄位放 SQL columns，例如距離、時間、配速、速度、心率、功率與訓練負荷。
- Garmin 可能變動或不固定的 metrics 放 JSONB，例如 `raw_metrics`、split `metrics` 與 `raw_profile`。
- 完整 raw payload 保留在 `activities.raw_json` 與 `user_profile_snapshots.raw_profile`，方便重跑 feature engineering。

建立 test database 後可以跑 DB tests：

```bash
docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" ai_running_coach_test || true'

python3 -m pytest -q tests/test_db_importer.py tests/test_db_repositories.py
```

也可以用 test profile 一次啟動 PostgreSQL、建立 test DB、執行 migration
並跑 DB tests：

```bash
docker compose --profile test up --abort-on-container-exit --exit-code-from db-tests db-tests
```

DB tests 會拒絕 `TEST_DATABASE_URL` 等於 `DATABASE_URL` 或 database
名稱不含 `test` 的連線，並只在 temporary schema 內建表，避免誤清主 DB。
沒有 test database 或缺少 `TEST_DATABASE_URL` / `TEST_POSTGRES_*` 設定時，
DB tests 會以環境缺失 skip；連到主 DB 或非 test DB 時，則屬安全防呆 skip。

## 專案結構

| 路徑 | 角色 |
| --- | --- |
| `run_pipeline.py` | CLI 入口，串接目標覆蓋參數與 pipeline runner。 |
| `src/pipeline/runner.py` | Garmin sync、DB fallback、preprocessing、Gemini 分析與 artifacts 輸出。 |
| `src/ingestion/garmin_client.py` | Garmin 登入、retry/backoff、profile/PR、活動詳細資料、分圈、心率/功率區間。 |
| `src/preprocessing/data_processor.py` | 正規化活動、配速/速度、進階活動指標與效率摘要。 |
| `src/preprocessing/coach_context.py` | 建立 deterministic coach context，並覆寫 AI report 中必須可信的 derived fields。 |
| `src/agents/coach.py` | 組合 coach prompt、呼叫 Gemini、解析 JSON report 與本機分析模式。 |
| `src/dashboard/server.py` | 本機 dashboard static server 與 read-only report API。 |
| `dashboard/` | 無 build step 的 dashboard 前端。 |
| `src/db/` | SQLAlchemy 2.0 models、session 與 repository layer。 |
| `src/services/db_importer.py` | 將 Garmin raw/user/processed 檔案匯入 PostgreSQL。 |
| `src/scripts/` | raw-only fetch 與 DB import CLI。 |
| `alembic/` | PostgreSQL migration。 |
| `prompts/coach.md` | 主要 AI coach prompt。 |
| `prompts/goal.md` | 預設賽事目標與訓練限制。 |
| `docs/dashboard.md` | Dashboard 資訊架構、欄位對應與 adapter 規則。 |
| `ai/` | AI coding workflow、reviewer、QA、security、dashboard 與 skills 的 canonical instructions（見 [`ai/README.md`](ai/README.md)）。 |
| `.cursor/`、`.github/`、`.codex/` | 各編輯器／Copilot 的薄 adapter，指向 `ai/`。 |
| `AGENTS.md`、`CLAUDE.md`、`.windsurfrules`、`GEMINI.md` | Cursor、Claude Code、Windsurf、Gemini 的根目錄入口，同樣指向 `ai/`。 |

## AI 設定來源

AI agent / skill 設定以 [`ai/README.md`](ai/README.md) 為單一來源，`.codex/`、
`.cursor/`、`.github/`、[`AGENTS.md`](AGENTS.md)、[`CLAUDE.md`](CLAUDE.md)、
[`GEMINI.md`](GEMINI.md) 都只做薄適配。預設回覆壓縮風格由
[`ai/skills/token-decrease/SKILL.md`](ai/skills/token-decrease/SKILL.md) 定義。

## 測試

一般 unit tests 不會呼叫真實 Garmin API。README 核心測試：

```bash
./scripts/test_core.sh
```

它實際執行的是：

```bash
python3 -m pytest -q \
  tests/test_data_processor.py \
  tests/test_qa_data_processor.py \
  tests/test_garmin_client_details.py \
  tests/test_garmin_client_activity_types.py \
  tests/test_fetch_garmin_raw.py \
  tests/test_goal_prompt.py \
  tests/test_runner.py \
  tests/test_coach.py \
  tests/test_coach_context.py \
  tests/test_dashboard_adapter.py \
  tests/test_dashboard_server.py
```

GitHub Actions 會在 PostgreSQL service 上執行 migration，並讓 DB tests 帶
`TEST_DATABASE_URL` 必跑；dashboard adapter tests 會優先用 Node.js 執行，
本機 macOS 仍可 fallback 到 `osascript`。

手動 Garmin smoke test 會呼叫真實 Garmin API，且需要本機 credentials：

```bash
python tests/scripts/garmin_client_smoke.py
```

## AI Agent 工作流

這個 repo 以 `ai/` 作為 AI coding instructions 的單一來源；各工具目錄
只放薄 adapter，**請在 `ai/` 維護規則，不要複製 workflow 正文**。

| 工具 | 入口 |
| --- | --- |
| 維護與新增 skill/agent | [`ai/README.md`](ai/README.md) |
| Cursor | [`.cursor/README-agents.md`](.cursor/README-agents.md)、[`AGENTS.md`](AGENTS.md) |
| GitHub Copilot | [`.github/README-agents.md`](.github/README-agents.md) |
| Codex | [`.codex/README-agents.md`](.codex/README-agents.md) |
| Gemini | [`GEMINI.md`](GEMINI.md) |
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Windsurf | [`.windsurfrules`](.windsurfrules) |

Canonical 文件：`ai/shared/instructions.md`（workflow）、
`reviewer` / `qa` / `security` / `frontend-dashboard` agent，以及
`ai/skills/` 下的 `python-review-qa-loop`、`git-change-conventions`、
`readme-pm-review`。

### 選用：Chrome DevTools MCP

若要讓 AI agent 更順地檢查 dashboard UI，可在本機 agent runtime
設定 Chrome DevTools MCP。這是 contributor DX 工具，不是執行主流程的必要條件。

Codex 範例設定：

```toml
[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest", "--channel", "stable", "--no-usage-statistics", "--no-performance-crux"]
```

設定後，AI agent 可用瀏覽器工具開啟 `http://127.0.0.1:8765/`、檢查
console/network、截圖並輔助 dashboard QA。建議使用隔離或 automation
profile，不要讓 MCP 工具檢查私人 Chrome session。更多 AI workflow
細節見 [`ai/README.md`](ai/README.md)。

## 注意事項

- `.env`、`.venv/`、`data/`、`output/` 與 `.DS_Store` 已被 git ignore。
- 不要把 Garmin 密碼、Gemini API key 或 PostgreSQL 密碼放進 tracked files。
- 主要最終報告是 JSON；CSV 是 processed activity backup。
- 設定 `GARMIN_DEBUG_ACTIVITY_DETAILS=1` 可以啟用活動 payload 除錯輸出。

# AI Running Coach

[![Tests](https://github.com/Andy-CH-BO-AN/AI-running-coach/actions/workflows/tests.yml/badge.svg)](https://github.com/Andy-CH-BO-AN/AI-running-coach/actions/workflows/tests.yml)

把 Garmin 訓練資料轉成 **deterministic facts → AI 教練判讀 → Dashboard / LINE 通知** 的個人訓練分析系統。

支援本機手動執行，也支援 GitHub Actions + Neon 的 cloud-scheduled Daily Run。這不是多使用者 SaaS；設計重點是單一跑者、資料可追溯、失敗模式明確，以及 AI 不負責憑空計算客觀數字。

## 核心理念

1. **Garmin 是原始事實來源**：保留 raw payload，不用 heuristic 偷改 Garmin 已解析出的 50m / 100m / split 結果。
2. **程式先算，AI 再解讀**：距離、日期、週量、zone、百分比、負荷與可追溯 facts 先由 Python deterministic 計算。
3. **LLM 負責 coaching，不負責當計算機**：Gemini 主要產生狀態、風險、賽事準備度、訓練建議與 evidence 文案。
4. **Cloud failure policy 是顯式狀態機**：Neon 掛掉時，不靠散落的 env flags 猜現在是哪種模式。
5. **可重跑、可 QA**：raw data、processed data、coach context、report 與 DB persistence 都有明確邊界。

## 目前能做什麼

- 從 Garmin Connect 抓取 profile、PR、近期活動、活動詳細資料、splits 與 swimming lengths。
- 支援 `running`、`lap_swimming`、`cycling`。
- 計算週訓練量、training load、心率 / 功率 Z1-Z5、跑姿、配速與交叉訓練摘要。
- 產生 deterministic `coach_context`，再交給 Gemini 產生 AI coach JSON report。
- Dashboard 顯示訓練回顧、週期化脈絡、四週訓練、強度分佈、下週課表與 evidence。
- 新活動可推送到 LINE，支援 persistent dedup、baseline seed、advisory lock 與 stateless fallback。
- PostgreSQL / Neon persistence 支援 idempotent import、local → mirror → cloud 切換與 parity validation。
- Cloud Daily Run 在 Neon migration 或 runtime persistence loss 時有明確降級政策。

## 架構總覽

```mermaid
flowchart TD
    G[Garmin Connect] --> P[ActivityPayloadProvider]
    P --> R[Deterministic preprocessing]
    R --> C[coach_context JSON]
    C --> A[Gemini coach]
    A --> O[AI report JSON]
    O --> D[Dashboard]
    C --> N[LINE notification]

    DB[(PostgreSQL / Neon)] <--> P
    DB <--> N

    DR[Cloud Daily Run] --> M[Migration preflight]
    M --> S{Run state}
    S -->|Normal| DB
    S -->|Degraded| P
    S -->|Persistence-loss| P
```

### Cloud Daily Run policy

Cloud scheduled execution 使用單一入口：

```bash
DATABASE_MODE=cloud python -m src.scripts.run_daily_pipeline
```

它會在同一個 Python process 內完成 migration preflight、state selection、Garmin sync、AI pipeline 與 LINE notification。

| State | 進入條件 | Activity window | Neon | LINE |
| --- | --- | ---: | --- | --- |
| **Normal** | migration 在 3 次內成功 | 75 | 可使用 | persistent dedup，既有 normal cap |
| **Degraded** | 3 次 migration 都是 transient connection failure | 10 | 整個 run 禁止 | stateless，最多 3 筆 |
| **Persistence-loss** | Normal 啟動後發生 transient Neon loss | 保留 75 | 當次 run 永久 revoke | stateless loss budget 3 |

重要 invariant：

- runtime transition 只有 `Normal → Persistence-loss`。
- 同一個 run 不會 reconnect Neon。
- 下一次 scheduled run 會重新做 migration preflight，可以再次進 Normal。
- authentication / configuration / schema / non-transient DB errors **fail closed**。
- Persistence-loss 只禁止後續 Neon I/O；已成功 materialize 到 memory 的資料可以繼續使用。
- 如果 Garmin incremental fetch 已完成、DB sync 才失敗，會用既有 materialized window + 已抓到的 Garmin updates 在 memory merge，不會再讀 Neon，也不會再打一次 Garmin。

詳細決策見 [`docs/adr/0001-neon-degraded-daily-pipeline.md`](docs/adr/0001-neon-degraded-daily-pipeline.md)。

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

最小設定：

```text
GARMIN_ACCOUNT=your_garmin_email
GARMIN_PASSWORD=your_garmin_password
GOOGLE_API_KEY=your_gcp_api_key
GOOGLE_GENAI_USE_VERTEXAI=true
```

Gemini client 支援：

- `GOOGLE_API_KEY`（優先）
- `GEMINI_KEY`
- `GEMINI_API_KEY`
- Vertex AI / ADC：搭配 `GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`

Gemini client 不會因為單純 import pipeline 就被建立；只有真正進 AI generation boundary 才需要 provider credentials。

### 3. 本機手動跑 pipeline

```bash
DATABASE_MODE=local python run_pipeline.py
```

或 mirror mode：

```bash
DATABASE_MODE=mirror python run_pipeline.py
```

手動入口可以自訂：

```bash
python run_pipeline.py \
  --activity-limit 75 \
  --fetch-limit 75 \
  --core-goal "半馬，目標 Sub-90" \
  --training-preferences "每週跑 4 天、週二游泳、週五重訓"
```

`run_pipeline.py` 只供 `local` / `mirror` 使用；`cloud` 會要求改走 Cloud Daily Run CLI。

### 4. Cloud scheduled run

```bash
DATABASE_MODE=cloud python -m src.scripts.run_daily_pipeline \
  --core-goal "$CORE_GOAL" \
  --training-preferences "$TRAINING_PREFERENCES"
```

Cloud Daily Run 不接受 `--activity-limit` 或 `--fetch-limit`，window 由 run policy 決定，caller 不能自行切換 mode。

GitHub Actions workflow：`.github/workflows/daily_pipeline.yml`。

### 5. 開 Dashboard

```bash
python3 -m src.dashboard.server
```

預設：`http://127.0.0.1:8765`

如果要分開跑 QA / UI review：

```bash
python3 -m src.dashboard.server --port 8765
python3 -m src.dashboard.server --port 8766
```

設計與欄位對應見 [`docs/dashboard.md`](docs/dashboard.md)。

## 輸出 artifacts

| 檔案 | 用途 |
| --- | --- |
| `data/raw/garmin_raw_YYYYMMDD.json` | Garmin activity raw payload、splits、swimming lengths |
| `data/raw/garmin_user_YYYYMMDD.json` | profile、PR、生理資料與偏好 |
| `data/processed/processed_YYYYMMDD.csv` | preprocessing 後的 normalized activities |
| `data/processed/coach_context_YYYYMMDD.json` | deterministic facts，AI 的事實層 |
| `output/ai_report_YYYYMMDD.json` | 最終 AI coach report，也是 Dashboard 資料來源 |

`coach_context` 會包含：

- Monday-based weekly buckets、週距離、時間與 training load。
- 每個 session 的距離、時間、HR、pace、training effect、segments。
- HR / power Z1-Z5 distribution。
- VO2max、最大 / 靜息心率、乳酸閾值心率與配速。
- cadence、ground contact、vertical oscillation、stride length 等跑姿 facts。
- swimming / cycling cross-training summary。
- 下週日期 seed、可訓練日、long-run preference。
- 可供 AI `evidence_links` 引用的 deterministic facts。

## Dashboard 重點

- **訓練計畫**：periodization、目標賽週數、下週核心與輔助課表。
- **訓練回顧**：優先顯示近期具代表性的刺激，不讓隔天恢復課蓋掉前一日主課。
- **強度分佈**：HR / power zones 與 AI assessment。
- **四週回顧**：跑步、游泳、自行車分開呈現。
- **Zone E**：pace zones 與有效跑步 splits 的跑姿資訊。
- **Evidence**：顯示 supporting sessions 與分段數據，不直接暴露 JSON path。

## PostgreSQL / Neon

### Database modes

| `DATABASE_MODE` | 行為 |
| --- | --- |
| `local` | app / manual pipeline / dashboard 使用本機 PostgreSQL |
| `mirror` | primary 仍是 local；commit 後同步 mirror tables 到 Neon 並驗 parity |
| `cloud` | Cloud Daily Run / dashboard 使用 Neon；scheduled policy 由 `daily_run.py` 控制 |

建議：

- app connection：`NEON_DATABASE_URL`（pooler）
- migration / sync / parity：`NEON_DATABASE_DIRECT_URL`（direct）

範例：

```text
DATABASE_MODE=local
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_local_password
DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach
LOCAL_DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach
NEON_DATABASE_URL=postgresql+psycopg://<user>:<password>@<pooler-host>/<db>?sslmode=require
NEON_DATABASE_DIRECT_URL=postgresql+psycopg://<user>:<password>@<direct-host>/<db>?sslmode=require
TEST_DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@localhost:5432/ai_running_coach_test
```

### 本機 DB

```bash
docker compose up -d postgres
alembic upgrade head
```

### 對 Neon migration

```bash
DATABASE_MIGRATION_TARGET=cloud alembic upgrade head
```

Cloud Daily Run 自己會在 preflight 用 Alembic Python interface 跑 `upgrade head`，不再依賴 shell script + `GITHUB_ENV` 傳 mode。

### Local → Mirror → Cloud

```text
DATABASE_MODE=local
        ↓
DATABASE_MODE=mirror
        ↓
DATABASE_MODE=cloud
```

第一次同步：

```bash
DATABASE_MIGRATION_TARGET=cloud alembic upgrade head
python -m src.scripts.sync_database_targets --source local --target cloud
```

只驗 parity：

```bash
python -m src.scripts.sync_database_targets \
  --source local \
  --target cloud \
  --validate-only
```

DB schema 採 hybrid design：常查詢欄位用 SQL columns，Garmin 易變 metrics 用 JSONB，完整 raw payload 留存供後續 feature engineering / replay。

## LINE notification

Cloud Daily Run 的 notification lifecycle：

```text
persistent dedup
    ↓
advisory lock
    ↓
format / send LINE
    ↓
record notification
```

如果 runtime persistence loss：

- Neon gate 立即 revoke。
- 同一個 run 不 reconnect。
- 已成功送出但 record 失敗的 activity 不會在同一 run 重送。
- 該 activity 會消耗一個 stateless loss slot。
- 後續 stateless delivery 受 loss budget 限制。
- 未來 run 在 persistence 仍不可用時，仍可能重複通知；這是目前接受的 tradeoff。

## 本機 replay / raw-only fetch

只用既有 Garmin JSON 重跑 report：

```bash
.venv/bin/python -m src.scripts.generate_local_report \
  --raw-file data/raw/garmin_raw_20260510.json \
  --user-file data/raw/garmin_user_20260510.json \
  --report-date 20260510
```

這條路徑不重新呼叫 Garmin，也不讀寫 PostgreSQL；但仍會呼叫 Gemini / Vertex AI。

只抓 raw Garmin：

```bash
python -m src.scripts.fetch_garmin_raw --limit 999
```

抓完直接 import DB：

```bash
python -m src.scripts.fetch_garmin_raw --limit 999 --import-db
```

Garmin Connect 可能有 rate limit；遇到 `429` 時不要快速連續重跑。

## Docker

Dashboard + PostgreSQL：

```bash
docker compose up -d postgres dashboard
```

常用：

```bash
docker compose build dashboard
docker compose down
```

## 測試

Core regression：

```bash
./scripts/test_core.sh
```

完整 pytest：

```bash
python -m pytest -q
```

DB test profile：

```bash
docker compose --profile test up \
  --abort-on-container-exit \
  --exit-code-from db-tests \
  db-tests
```

測試原則：

- 一般 unit tests 不呼叫真實 Garmin API。
- test DB guard 會拒絕 primary DB / 非 test database。
- Cloud Daily Run tests 驗 migration retry、state transition、Neon revoke、75/10 activity window、stateless notification 與 secret-safe errors。
- CI 使用 PostgreSQL service 跑 migration + core + DB tests。

真實 Garmin smoke test：

```bash
python tests/scripts/garmin_client_smoke.py
```

## 專案結構

| 路徑 | 角色 |
| --- | --- |
| `run_pipeline.py` | local / mirror 手動 CLI |
| `src/scripts/run_daily_pipeline.py` | cloud-scheduled Daily Run CLI |
| `src/pipeline/daily_run.py` | Cloud Daily Run policy、migration preflight、state machine、Neon gate |
| `src/pipeline/runner.py` | deterministic / AI pipeline orchestration |
| `src/pipeline/activity_payloads.py` | DB / Garmin payload acquisition、sync 與 fallback |
| `src/preprocessing/coach_context.py` | deterministic coach context |
| `src/agents/coach.py` | Gemini provider、retry、JSON parsing |
| `src/services/report_generator.py` | lazy AI boundary + deterministic report enforcement |
| `src/notifications/` | LINE formatting、delivery、dedup、advisory lock |
| `src/db/` | SQLAlchemy models、repositories、sessions、sync |
| `src/dashboard/server.py` | read-only Dashboard server |
| `dashboard/` | 無 build step 的 Dashboard frontend |
| `alembic/` | PostgreSQL migrations |
| `prompts/coach.md` | coach prompt |
| `prompts/goal.md` | default goal / training constraints |
| `docs/adr/` | architecture decisions |
| `ai/` | AI coding workflow canonical instructions |

## Architecture notes

目前已完成的幾個主要邊界：

- Garmin parsing / activity policy 與 orchestration 分離。
- artifact persistence 集中到 service boundary。
- deterministic coach context 與 Gemini generation 分離。
- DB settings / repository / sync target responsibilities 分離。
- Cloud Daily Run policy 集中 migration、run state、activity window、Neon capability 與 notification transition。
- manual local/mirror pipeline 與 cloud scheduled pipeline 明確分開。

下一步若要繼續深化，優先考慮：

1. deterministic session facts 的 end-to-end ownership。
2. notification render / pagination / delivery lifecycle 再集中。
3. Activity window normalization，但必須保留 Garmin raw quirks，不做過度 heuristic 修正。

## AI Agent 工作流

AI coding instructions 以 [`ai/README.md`](ai/README.md) 為單一來源。

| 工具 | 入口 |
| --- | --- |
| Cursor | [`.cursor/README-agents.md`](.cursor/README-agents.md)、[`AGENTS.md`](AGENTS.md) |
| GitHub Copilot | [`.github/README-agents.md`](.github/README-agents.md) |
| Codex | [`.codex/README-agents.md`](.codex/README-agents.md) |
| Gemini | [`GEMINI.md`](GEMINI.md) |
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Windsurf | [`.windsurfrules`](.windsurfrules) |

Canonical workflow / reviewer / QA / security / skills 都維護在 `ai/`，不要把相同規則複製到各 adapter。

## 目前限制

- Garmin API 是非官方 integration surface，登入、MFA 與 rate limit 可能改變。
- 部分 Garmin 指標依裝置 / activity type 而異，歷史活動可能缺欄位。
- Dashboard 目前是 read-only report viewer。
- Stateless notification 無 durable dedup，因此未來 run 可能重複發送。
- 專案以單一跑者 / self-hosted workflow 為主，不提供 multi-tenant auth 或 public SaaS API。

## License

目前 repository 未另外聲明 license；使用或散布前請先確認專案授權方式。

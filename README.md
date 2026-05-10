# AI Running Coach

AI Running Coach is a local Garmin-to-AI training analysis pipeline. It fetches recent Garmin Connect activities, normalizes activity metrics, sends the structured data to Gemini, and writes a Markdown coaching report.

The current training prompt is focused on a 1500m goal, recent 1-2 week freshness, training load, heart-rate zones, running mechanics, and cross-training context.

## What It Does

- Fetches Garmin profile, personal records, recent activities, splits, and activity detail payloads.
- Currently ingests `running` and `lap_swimming` activities from Garmin Connect.
- Normalizes running, swimming, and cycling-style metrics in preprocessing; cycling support exists in the processor, but Garmin cycling ingestion is currently disabled in `src/ingestion/garmin_client.py`.
- Saves raw Garmin activity and user data under `data/raw/`.
- Saves processed activity rows as CSV under `data/processed/`.
- Generates the final AI coaching report as Markdown under `output/`.
- Keeps AI agent workflow rules in shared Markdown so GitHub Copilot, Codex, and future adapters can reuse the same reviewer and QA instructions.

## Data Pipeline

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

## Project Layout

- `run_pipeline.py`: CLI entrypoint that adds `src/` to `sys.path` and runs the pipeline.
- `src/pipeline/runner.py`: Orchestrates ingestion, preprocessing, Gemini analysis, and file output.
- `src/ingestion/garmin_client.py`: Handles Garmin login, retry/backoff, profile/PR fetches, activity details, splits, HR zones, and power zones.
- `src/preprocessing/data_processor.py`: Calculates pace/speed, formats metrics, normalizes advanced activity data, and derives efficiency summaries.
- `src/agents/coach.py`: Builds the Gemini prompt context and writes local analysis reports.
- `prompts/coach.md`: Main coaching prompt.
- `prompts/goal.md`: Current race goal and training constraints.
- `data/raw/`: Ignored local Garmin raw JSON output.
- `data/processed/`: Ignored local processed CSV output.
- `data/sample/`: Ignored local raw API samples for debugging.
- `output/`: Ignored local Markdown reports.
- `ai/shared/`: Canonical AI workflow, reviewer, and QA instructions.
- `.github/`: GitHub Copilot adapters that point to `ai/shared/`.
- `.codex/`: Codex adapters that point to `ai/shared/`.

## Setup

1. Create and activate a Python environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create a local `.env` file.

```text
GARMIN_ACCOUNT=your_garmin_email
GARMIN_PASSWORD=your_garmin_password
GEMINI_KEY=your_gemini_api_key
```

## Run

Run the full Garmin ingestion and AI analysis pipeline:

```bash
python run_pipeline.py
```

Expected local outputs:

- `data/raw/garmin_raw_YYYYMMDD.json`
- `data/raw/garmin_user_YYYYMMDD.json`
- `data/processed/processed_YYYYMMDD.csv`
- `output/ai_report_YYYYMMDD.md`

Garmin login can require manual verification or hit rate limits. The ingestion code uses retry/backoff, but repeated API calls should still be avoided when debugging.

## Local Analysis

To analyze existing local files without fetching Garmin again, use `run_local_analysis` from `src/agents/coach.py` with a processed CSV, raw user JSON, and optional goal prompt.

Example:

```bash
python src/agents/coach.py
```

The hardcoded file names in the `__main__` block are examples, so update them before using that path.

## Tests

Run the automated unit tests:

```bash
PYTHONPATH=. pytest -q tests/test_garmin_client_details.py
```

Current tracked tests include:

- `tests/test_garmin_client_details.py`: Unit tests for Garmin activity detail parsing, nested metric extraction, and time-in-zone fallback payloads.
- `test_garmin_client.py`: Manual Garmin smoke-test script that calls the real Garmin API and requires local credentials.

`pytest -q` may try to collect local/manual scripts at the repo root. Prefer the explicit unit-test command above for automation, and use the manual Garmin script sparingly:

```bash
python test_garmin_client.py
```

## AI Agent Workflow

This repo uses shared Markdown as the single source of truth for AI coding workflow instructions.

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

When adding Claude, Gemini, or another tool later, create a thin adapter that points back to `ai/shared/` instead of duplicating reviewer or QA rules.

## Notes

- `.env`, `data/`, `output/`, `.venv/`, and CSV files are ignored by git.
- The primary final report is Markdown, not CSV. CSV files are processed-data backups.
- Some advanced Garmin metrics depend on device support and may be missing for older activities.
- `GARMIN_DEBUG_ACTIVITY_DETAILS=1` enables extra activity payload debugging in `garmin_client.py`.

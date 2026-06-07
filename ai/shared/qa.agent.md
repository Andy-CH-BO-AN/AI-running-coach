# Shared QA Instructions

Use this as the canonical QA guidance for every platform adapter.

## Responsibilities

- Map each change to the smallest reliable QA scope before running tests.
- Save API responses and outputs to files for debugging and reproduction.
- Do not call the Garmin API repeatedly; save responses and reuse them
  for testing and debugging.
- Add and maintain unit, integration, and boundary tests.
- Execute tests, capture failures, and produce reproduction steps.
- Suggest minimal code changes or test fixes when confident.

## Coverage Matrix

Use this matrix to decide whether existing tests cover the change and what
extra QA is needed.

### Functional tests

Required for changes to deterministic context, prompts, runner behavior,
dashboard adapters, ingestion, services, or schemas.

- Cover happy path scenarios.
- Cover alternative flows and missing or partial data.
- Cover input validation and rejected inputs.
- Assert expected outputs, not only that code runs.
- Check preconditions and postconditions when state changes.
- Prefer deterministic Python tests for facts such as distance, dates,
  weekly aggregates, pace, heart-rate zones, and DB-derived metrics.
- Changes to `src/preprocessing/coach_context.py`,
  `coach_context_types.py`, or `coach_context_utils.py` should be
  validated by `tests/test_coach_context.py`.
- Changes to `dashboard/reportAdapter.js` should be validated by
  `tests/test_dashboard_adapter.py` — this is the primary adapter
  regression baseline (300+ test cases covering derived metrics,
  evidence links, session selection, pace formatting, and edge cases).

### UX tests

Required for changes under `dashboard/`, `src/dashboard/`, or any
browser-visible behavior.

- Check each step in the user flow touched by the change.
- Check navigation between steps, report selection, expand/collapse controls,
  and any visible state transitions.
- Check data persistence across steps when UI state or selected reports should
  survive interaction.
- Check error handling at each stage, including empty report lists, invalid
  reports, missing fields, and network failures.
- Check exit points and cancellation scenarios when a flow provides them.
- Verify desktop and mobile layouts for readable text, no overlap, and no
  clipped critical content.

### DB tests

DB tests must use only a test database.

- Use `TEST_DATABASE_URL` or `TEST_POSTGRES_*`.
- Refuse to run when the test DB URL equals `DATABASE_URL`.
- Refuse to run when the database name does not contain `test`.
- Use isolated schemas or equivalent cleanup so tests do not share state.
- Cover create paths with valid and invalid data, required fields, and
  defaults when the changed code owns them.
- Cover reads for single records, multiple records, filtering, and sorting
  when the changed code owns those query paths.
- Cover updates for partial updates, full updates, and concurrent/idempotent
  updates when supported.
- Cover deletes for single delete, bulk delete, soft delete, and cascade
  effects when supported. If a delete mode is not implemented by the product,
  report it as not applicable instead of inventing a fake test.

### Regression tests

Run a regression scope that matches the change risk.

- Always include core functionality touched by the change.
- Include integration points between preprocessing, DB persistence, runner,
  dashboard server, dashboard adapter, and prompts when relevant.
- Validate critical user paths: fetch/import data, build deterministic coach
  context, generate or enforce report contracts, serve dashboard JSON, render
  dashboard from latest report.
- Check side effects of recent changes, especially schema/contract shifts.
- Include smoke tests for quick validation before deeper checks.
- When dashboard adapter or frontend behavior changes, run
  `tests/test_dashboard_adapter.py` as part of the regression scope.
- When UI/UX changes are involved, cross-reference the UX audit checklist
  in `ai/shared/uiux.agent.md` for visual and interaction
  review criteria.

## UI Automation

- Use Chrome DevTools MCP for dashboard QA when available. Open
  `http://127.0.0.1:8765/`, inspect accessibility snapshots, console errors,
  network failures, desktop/mobile viewports, key interactions, and screenshots.
- QA port is fixed to `8765`. Do not reuse the UI/UX review port `8766`.
- Keep Chrome MCP on the isolated/default automation profile. Do not inspect
  private user browser sessions unless explicitly requested.
- If Chrome MCP is unavailable, use the headless Chrome commands in
  `ai/shared/uiux.agent.md`.
- Save screenshots, traces, or notes under `tests/reports/` with descriptive
  names and dates.
- Do not add Selenium for this repo by default. It adds driver management
  overhead without clear benefit for the local dashboard.
- Do not add Playwright by default for one-off QA. If the project needs
  committed, repeatable UI automation in CI, prefer Playwright over Selenium
  because it provides stable browser control, trace artifacts, screenshots,
  and simpler cross-browser setup. Add it only with an explicit test-runner
  setup and documented install command.
- Until Playwright is adopted, treat Chrome MCP plus headless Chrome screenshots
  as the dashboard UI regression path.

## Testcase Maintenance

- Keep tests that protect contracts, safety, deterministic facts, or visible
  behavior, even when they look narrow.
- Remove or rewrite a testcase only when it verifies deleted behavior, relies
  on an obsolete schema, contradicts current requirements, or locks a harmless
  implementation detail without protecting safety or contract behavior.
- When removing a testcase, explain the obsolete assumption and identify the
  replacement coverage, if any.

## Project Notes

- Run `scripts/test_core.sh` for the core non-DB regression suite when the
  change touches Python code, contracts, runner behavior, prompts, or dashboard
  adapter/server behavior.
- `scripts/test_core.sh` does **not** include DB-layer tests. When the
  change touches DB logic, run these separately:
  `tests/test_db_importer.py`, `tests/test_db_mirror.py`,
  `tests/test_db_sync.py`, `tests/test_db_repositories.py`.
- To test `src/ingestion/garmin_client.py`, use `.venv/bin/activate`
  and `python run_pipeline.py`.
- To test `src/preprocessing/data_processor.py`, use
  `data/sample/raw_data_sample_xxx.json` as input.
- If `data/sample/raw_data_sample_xxx.json` is missing, run
  `tool/save_raw_data.py` to generate it.
- Garmin login API may return 429 twice, then continue only after a long
  pause. After running `python run_pipeline.py` or
  `.venv/bin/python -m src.scripts.fetch_garmin_raw --limit 999 --import-db`,
  wait 3-8 minutes before assuming the process is stuck. Repeated reruns
  can make Garmin rate limiting worse.
- Report issues with priority labels: `critical`, `normal`, `minor`,
  `suggestion`.
- Tell developers that critical issues will block the PR merge.
- Save test scripts and reports in `tests/scripts/` or `tests/reports/`
  for future reference.

## Output

- State which coverage areas were in scope: functional, UX, DB, regression.
- List commands run and whether each passed, failed, or skipped.
- Include reproduction steps.
- Include failing output when available.
- Include artifact paths when screenshots, traces, saved responses, or reports
  were produced.
- Include skipped checks and the reason they were skipped.
- Keep fixes minimal and focused on the failing behavior.

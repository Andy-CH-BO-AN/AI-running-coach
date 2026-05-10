# Shared QA Instructions

Use this as the canonical QA guidance for every platform adapter.

## Responsibilities

- Save API responses and outputs to files for debugging and reproduction.
- Do not call the Garmin API repeatedly; save responses and reuse them
  for testing and debugging.
- Add and maintain unit, integration, and boundary tests.
- Execute tests, capture failures, and produce reproduction steps.
- Suggest minimal code changes or test fixes when confident.

## Project Notes

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

- Include reproduction steps.
- Include failing output when available.
- Keep fixes minimal and focused on the failing behavior.

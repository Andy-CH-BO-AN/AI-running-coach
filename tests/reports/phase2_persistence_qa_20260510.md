# Phase 2 Persistence QA Report - 2026-05-10

Scope:
- Phase 2 PostgreSQL persistence layer
- Raw-only Garmin fetch CLI
- README / QA docs
- Unit and DB tests

Garmin API:
- Not called during this QA pass.
- Raw-only fetch behavior was verified through mocked unit tests only.

Database safety:
- Main local DB was queried only.
- Write tests used `TEST_DATABASE_URL` pointing at the local `ai_running_coach_test` database.
- DB tests create an isolated temporary schema in the test database and clean up that schema after the run.
- `TEST_DATABASE_URL` is refused if it matches `DATABASE_URL` or if the database name does not contain `test`.

Commands and results:

```bash
docker compose ps
```

Result: `postgres` service was healthy.

```bash
alembic current
```

Result: `20260510_0001 (head)`.

```bash
python3 -m src.scripts.import_garmin_files --help
python3 -m src.scripts.fetch_garmin_raw --help
```

Result: both CLI help commands succeeded.

```bash
python3 -m pytest -q \
  tests/test_data_processor.py \
  tests/test_qa_data_processor.py \
  tests/test_garmin_client_details.py \
  tests/test_runner.py \
  tests/test_coach.py \
  tests/test_fetch_garmin_raw.py
```

Result: `20 passed`.

```bash
python3 -m pytest -q
```

Result after fixing test pandas stub isolation in `tests/test_runner.py`: `20 passed, 7 skipped`.

```bash
docker compose exec -T postgres sh -c 'createdb -U postgres ai_running_coach_test 2>/dev/null || true'

python3 -m pytest -q tests/test_db_importer.py tests/test_db_repositories.py
```

Result: `7 passed`.

```bash
alembic upgrade head --sql
```

Result: static PostgreSQL migration SQL generated successfully.

```bash
docker compose exec -T postgres psql -U postgres -d ai_running_coach_test \
  -c "select schema_name from information_schema.schemata where schema_name like 'test_schema_%';"
```

Result: no temporary test schemas remained.

Main DB query-only snapshot:

```text
users: 1
activities: 620
activity_splits: 4816
swimming_lengths: 413
alembic_version: 20260510_0001
```

Findings:
- No critical or normal QA issues found.
- Minor environment note: `.venv` currently does not have `pytest`; `python3 -m pytest` works in the current machine environment. README already documents installing requirements after activating the venv.

#!/usr/bin/env bash

set -euo pipefail

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

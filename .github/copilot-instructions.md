---
name: copilot-workflow
description: |
  Use when: coordinating code changes, code review, and QA testing.
  This instruction enforces a strict review→QA loop for any code or
  test changes: after making changes, get a reviewer approval, then
  run QA; if either reviewer or QA requests changes, iterate until
  both explicitly approve.
applyTo:
  - "src/**"
  - "tests/**"
  - "**/*.py"
  - ".github/**"
auto_run_tests: true
auto_apply_fixes: true
prompt_before_actions: false

instructions: |
  - Scope: apply for feature work, bug fixes, and test changes that
    modify files under `src/` or `tests/`.

  - Workflow (strict):
    1. Implement the minimal change required to address the task or
       bug. Keep changes focused; avoid unrelated refactors.
    2. Run the project's test command locally. Prefer `pytest -q` if
       `pytest` is available; otherwise use the project's configured
       test runner. Capture failing test output and stack traces.
    3. Create a minimal patch/commit containing only the change and
       test updates. Provide a short summary of what you changed and
       why.
    4. Hand off the patch to the `reviewer` agent (the reviewer agent
       defined in `.github/agents/reviewer.agent.md`). Include:
       - failing test output (if any)
       - a brief reproduction step or small script to reproduce
       - the minimal patch/commit
    5. Wait for explicit reviewer feedback. Treat the phrases
       "approved", "LGTM", or "pass" as reviewer approval. Any
       other feedback should be treated as a request for changes.
    6. If reviewer requests changes, implement the fixes, run tests,
       and repeat step 4. Do not proceed to QA until reviewer gives
       explicit approval.
    7. After reviewer approval, hand off to the `qa` agent (the QA
       agent defined in `.github/agents/qa.agent.md`). Instruct QA to
       run the full test suite and perform exploratory checks.
    8. If QA reports failures or issues, implement fixes and return
       to step 4 (reviewer). Repeat the review→QA loop until both
       reviewer and QA report success.
    9. When both reviewer and QA approve, run the full test suite one
       final time and summarize the commands and results in a short
       closing comment.

  - Interaction rules:
    - Always prefer minimal, incremental patches so each review cycle
      is small and focused.
    - Document test commands used, environment, and any non-obvious
      reproduction steps.
    - Avoid automatically merging; leave the final merge/PR action to
      the human maintainer unless instructed otherwise.

notes: |
  - The `reviewer` and `qa` agents are the custom agents in
    `.github/agents/reviewer.agent.md` and `.github/agents/qa.agent.md`.
  - This instruction assumes local capability to run tests. If tests
    cannot be run, report why and provide clear reproduction steps.

examples:
  - "Write feature X in `src/ingestion/garmin_client.py`, run tests, send to reviewer, iterate until approved, then run QA."
  - "Fix failing tests in `src/preprocessing/data_processor.py` and follow the review→QA loop until green."
---

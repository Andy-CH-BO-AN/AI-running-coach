---
name: python-review-qa-loop
description: Use when working on Python code changes that should follow this repo's shared review and QA loop. Read the shared workflow docs, make the smallest viable patch, run relevant tests, capture results, and route DB, credentials, secrets, or Garmin password related changes through the shared security guidance.
---

# Python Review QA Loop

Use this skill when the task touches Python code, tests, repo workflow
docs, or related project automation.

## Read first

- `ai/shared/instructions.md`
- `ai/shared/reviewer.agent.md`
- `ai/shared/qa.agent.md`

## Escalate to security review

If the task touches any of the following, also read
`ai/shared/security.agent.md` before editing or validating:

- database schema, migrations, DB connection settings, import scripts,
  destructive test setup, or persistence logic
- credentials, tokens, API keys, `.env` handling, `.env.example`,
  secret placeholders, or connection strings
- Garmin account handling, Garmin password flow, or any workflow that
  could expose Garmin credentials

## How to apply reviewer, QA, and security guidance

Do not assume the platform will automatically spawn separate reviewer,
QA, or security agents just because this skill is active.

Instead, apply the repo's review loop explicitly:

1. Read the relevant shared guidance files.
2. Perform one reviewer pass using `ai/shared/reviewer.agent.md`.
   Reviewer scope is changed-code review: inspect the diff and affected
   context for correctness, regressions, maintainability, and security-adjacent
   risks. Do not ask reviewer to rerun broad or full regression suites.
   Reviewer may run only tiny targeted checks when needed to confirm a
   suspected issue.
3. Perform one QA pass using `ai/shared/qa.agent.md`.
   QA scope is test coverage and regression validation: use the test commands
   already run by the implementer/reviewer to avoid duplicate work, then fill
   the remaining coverage gaps and run broader regression only when needed.
4. If the task touches DB, secrets, `.env`, credentials, or Garmin
   password/account flows, perform one security pass using
   `ai/shared/security.agent.md`.

## Mandatory Reviewer → QA delegation

For every Python change, including Python test changes, use explicit
delegation whenever sub-agent tooling is available. This is mandatory;
the user does not need to request it.

1. Spawn a fresh reviewer sub-agent for the changed-code review.
2. Wait for the reviewer result and address any blocking findings.
3. Spawn a fresh QA sub-agent for coverage and regression validation.
4. Do not treat self-review, a simulated role, or one agent doing both
   passes as a substitute for Reviewer → QA.

Run reviewer before QA. Use separate agents even when the change is
small. If a worker slot is temporarily unavailable, wait for a slot and
continue the sequence; only run the passes yourself when sub-agent
tooling is actually unavailable for the whole task. Report that fallback
clearly.

For security review, delegate to a separate security agent whenever the
runtime supports it. If the user also asks for UI/UX review and the
runtime supports delegation, spawn a separate UI/UX agent too.

Only execute the passes in a single Codex run when sub-agent tooling is
actually unavailable. In that fallback case, report the limitation
clearly.

## Workflow

1. Read the shared workflow docs listed above.
2. Inspect the affected code and make the smallest viable change.
3. Run the most relevant tests locally. Prefer targeted `pytest -q`
   commands before broader suites.
4. Capture failures, stack traces, and reproduction steps when tests do
   not pass.
5. When sub-agents are available, spawn a fresh reviewer using
   `ai/shared/reviewer.agent.md`; wait for its result and resolve blocking
   findings. Tell the reviewer which tests have already run and ask it to
   focus on changed code instead of repeating QA's regression work.
6. After reviewer completion, spawn a fresh QA agent using
   `ai/shared/qa.agent.md`; tell QA which tests have already run so it can
   target unvalidated behavior, missing scenarios, and final regression
   instead of duplicating reviewer checks.
   Save durable artifacts in `tests/reports/` or `tests/scripts/` when helpful.
7. If security review was triggered, run a separate security pass and
   report those checks explicitly.
8. Summarize what changed, what was tested, and any remaining risk from
   reviewer, QA, and security checks.

## Browser-assisted QA

If the task touches dashboard UI, browser-visible output, static assets, or
frontend adapter behavior:

1. Prefer Chrome DevTools MCP when available.
2. Start the local dashboard server on the role-specific port.
   - QA uses `python3 -m src.dashboard.server --port 8765`
   - UI/UX review uses `python3 -m src.dashboard.server --port 8766`
3. Open the matching URL through the browser tool.
   - QA uses `http://127.0.0.1:8765/`
   - UI/UX review uses `http://127.0.0.1:8766/`
4. Check the rendered page, console messages, network requests, and responsive
   desktop/mobile layout.
5. Save useful screenshots or reports under `tests/reports/`.

If Chrome MCP is unavailable, use the headless Google Chrome commands in
`ai/shared/uiux.agent.md`.

## Output expectations

- Keep fixes minimal and incremental.
- Lead review feedback with findings when doing review-only work.
- Call out exact test commands used.
- For dashboard/browser work, state whether Chrome MCP or headless Chrome was
  used and where artifacts were saved.
- State clearly when tests were not run or when Garmin API calls were
  intentionally avoided.
- When you do reviewer / QA / security passes in one run, label them
  clearly so the user can see each stage happened.

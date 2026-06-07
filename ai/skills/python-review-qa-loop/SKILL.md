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
3. Perform one QA pass using `ai/shared/qa.agent.md`.
4. If the task touches DB, secrets, `.env`, credentials, or Garmin
   password/account flows, perform one security pass using
   `ai/shared/security.agent.md`.

If the runtime supports explicit delegation and the user asked for it,
you must delegate those passes to separate reviewer / QA / security
agents instead of only simulating those roles yourself. If the user
also asks for UI/UX review and the runtime supports delegation, spawn a
separate UI/UX agent too.

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
5. Run a reviewer pass using `ai/shared/reviewer.agent.md`.
6. Run a QA pass using `ai/shared/qa.agent.md` and save durable artifacts in
   `tests/reports/` or `tests/scripts/` when helpful.
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

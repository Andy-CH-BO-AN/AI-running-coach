# Shared AI Workflow

This repository uses a single source of truth for agent behavior.
Platform-specific files in `.github/` and `.codex/` should stay thin and
point back to these shared markdown files.

## Scope

This workflow applies to feature work, bug fixes, and test changes that
touch `src/`, `tests/`, or Python files.

## Workflow

1. Implement the minimal change required to address the task or bug.
2. Run the project test command locally. Prefer `pytest -q` if
   available; otherwise use the configured test runner.
3. Capture failing test output and stack traces when tests fail.
4. If the change touches DB logic, migrations, credentials, secrets,
   `.env` handling, or Garmin password/account flows, review
   `ai/shared/security.agent.md` and include a security pass before
   final sign-off.
5. Send the patch to the reviewer agent first.
6. If reviewer approves, hand off to QA for the full test suite and
   exploratory checks.
7. If reviewer or QA requests changes, fix the issue and repeat the
   review→QA loop until both explicitly approve.
8. When both approve, run the full test suite one final time and
   summarize the commands and results.

## Interaction Rules

- Keep patches minimal and incremental so each review cycle stays small.
- Document test commands used, environment details, and non-obvious
  reproduction steps.
- Use the canonical Git change naming skill in
  `ai/skills/git-change-conventions/SKILL.md` whenever creating a
  branch, naming a PR, or writing commit messages.
- Avoid automatic merging; leave the final merge or PR action to the
  human maintainer unless instructed otherwise.
- If tests cannot be run, report why and provide clear reproduction
  steps instead.

## Canonical Files

- `ai/shared/instructions.md`
- `ai/shared/reviewer.agent.md`
- `ai/shared/qa.agent.md`
- `ai/shared/security.agent.md`
- `ai/skills/git-change-conventions/SKILL.md`

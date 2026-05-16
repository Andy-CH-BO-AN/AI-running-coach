---
name: codex-workflow
description: |
  Use when coordinating code changes, code review, and QA testing in
  Codex. This is the Codex adapter for the shared workflow docs.
applyTo:
  - "src/**"
  - "tests/**"
  - "**/*.py"
  - ".github/**"
  - ".codex/**"
  - ".cursor/**"
  - "ai/**"
auto_run_tests: true
auto_apply_fixes: true
prompt_before_actions: false

instructions: |
  Canonical workflow: [`ai/shared/instructions.md`](../ai/shared/instructions.md)
  Reviewer guidance: [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
  QA guidance: [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
  Security guidance: [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)

  If a task touches DB logic, migrations, credentials, secrets, `.env`
  handling, or Garmin password/account flows, include the shared
  security guidance in the review loop.

  Optional on-demand skill: use
  [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
  only when the user explicitly asks for a product-manager style review
  of `README.md`.

  Git branch / PR / commit naming guidance: use
  [`ai/skills/git-change-conventions/SKILL.md`](../ai/skills/git-change-conventions/SKILL.md)
  whenever creating a branch, naming a PR, or writing commit messages.

  Frontend dashboard guidance: use
  [`ai/shared/frontend-dashboard.agent.md`](../ai/shared/frontend-dashboard.agent.md)
  when designing or implementing the AI running coach dashboard,
  visualization adapters, weekly derived metrics, or evidence-link UI.

  Keep this adapter thin so the shared docs stay the single source of truth.

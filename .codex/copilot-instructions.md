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
  - "ai/**"
auto_run_tests: true
auto_apply_fixes: true
prompt_before_actions: false

instructions: |
  Canonical workflow: [`ai/shared/instructions.md`](../ai/shared/instructions.md)
  Reviewer guidance: [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
  QA guidance: [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)

  Keep this adapter thin so the shared docs stay the single source of truth.

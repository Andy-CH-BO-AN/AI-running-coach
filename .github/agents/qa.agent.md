---
name: qa
display_name: "QA Engineer"
description: |
  GitHub adapter for the shared QA workflow. Use the shared QA
  instructions for test strategy, reproduction, and reporting.
applyTo:
  - "src/**"
  - "tests/**"
  - "**/*.py"
  - ".github/**"
  - ".codex/**"
  - "ai/**"
tools:
  allow:
    - read_files
    - write_files
    - run_tests
  block:
    - internet
    - install_packages
auto_run_tests: true
auto_apply_fixes: true
prompt_before_actions: false
persona:
  - role: "Senior QA Engineer"
instructions: |
  Canonical QA instructions: [`ai/shared/qa.agent.md`](../../ai/shared/qa.agent.md)

  Keep this adapter minimal and defer behavior details to the shared
  QA doc.
---

---
name: reviewer
display_name: "Code Reviewer"
description: |
  Codex adapter for the shared reviewer workflow. Use the shared
  reviewer instructions for review scope, style, and output format.
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
  - role: "Senior Engineer / Code Reviewer"
instructions: |
  Canonical reviewer instructions: [`ai/shared/reviewer.agent.md`](../../ai/shared/reviewer.agent.md)

  Keep this adapter minimal and defer behavior details to the shared
  reviewer doc.

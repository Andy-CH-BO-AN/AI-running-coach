---
name: uiux
display_name: "Dashboard UI/UX Review Agent"
description: |
  GitHub adapter for the shared AI running coach dashboard UX audit workflow.
  Use the shared UX audit instructions for accessibility, responsiveness,
  data correctness, and visual quality review.
applyTo:
  - "src/**"
  - "prompts/**"
  - "output/**"
  - "ai/**"
  - ".codex/**"
  - ".github/**"
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
  - role: "Senior UI/UX Review Engineer"
instructions: |
  Canonical UX audit instructions: [`ai/shared/uiux.agent.md`](../../ai/shared/uiux.agent.md)

  Keep this adapter minimal and defer behavior details to the shared
  UX audit doc.
---

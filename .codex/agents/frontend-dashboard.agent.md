---
name: frontend-dashboard
display_name: "Frontend Dashboard Agent"
description: |
  Codex adapter for the shared AI running coach dashboard workflow.
  Use the shared frontend dashboard instructions for visualization scope,
  adapter rules, evidence links, and UI expectations.
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
  - role: "Senior Product Designer / Frontend Data Visualization Engineer"
instructions: |
  Canonical frontend dashboard instructions: [`ai/shared/frontend-dashboard.agent.md`](../../ai/shared/frontend-dashboard.agent.md)

  Keep this adapter minimal and defer behavior details to the shared
  frontend dashboard doc.
---

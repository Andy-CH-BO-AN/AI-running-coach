---
name: security
display_name: "Security Reviewer"
description: |
  GitHub Copilot adapter for shared security review. Use the shared
  security instructions for secret scanning, config safety, DB safety,
  and API risk checks.
applyTo:
  - "src/**"
  - "tests/**"
  - "**/*.py"
  - "**/*.md"
  - ".github/**"
  - ".codex/**"
  - "ai/**"
  - "docker-compose.yml"
  - "alembic.ini"
  - ".env.example"
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
  - role: "Senior Security Engineer"
instructions: |
  Canonical security instructions: [`ai/shared/security.agent.md`](../../ai/shared/security.agent.md)

  Keep this adapter minimal and defer behavior details to the shared
  security doc.

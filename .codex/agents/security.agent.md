---
name: security
description: Codex adapter for shared security review. Use the shared security instructions for secret scanning, config safety, DB safety, and API risk checks.
---

# Codex Adapter: Security Reviewer

## Settings
- **Apply to**:
  - `src/**`
  - `tests/**`
  - `**/*.py`
  - `**/*.md`
  - `.github/**`
  - `.codex/**`
  - `ai/**`
  - `docker-compose.yml`
  - `alembic.ini`
  - `.env.example`
- **Auto run tests**: true
- **Auto apply fixes**: true
- **Prompt before actions**: false
- **Persona**: Senior Security Engineer

## Instructions

Canonical security instructions: [security.agent.md](file:///Users/chenboan/Desktop/code/AI-running-coach/ai/shared/security.agent.md)

Keep this adapter minimal and defer behavior details to the shared security doc.

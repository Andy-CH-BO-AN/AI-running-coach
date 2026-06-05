---
name: reviewer
description: GitHub adapter for the shared reviewer workflow. Use the shared reviewer instructions for review scope, style, and output format.
---

# GitHub Adapter: Code Reviewer

## Settings
- **Apply to**:
  - `src/**`
  - `tests/**`
  - `.github/**`
  - `.codex/**`
  - `ai/**`
  - `**/*.py`
- **Auto run tests**: true
- **Auto apply fixes**: true
- **Prompt before actions**: false
- **Persona**: Senior Engineer / Code Reviewer

## Instructions

Canonical reviewer instructions: [reviewer.agent.md](file:///Users/chenboan/Desktop/code/AI-running-coach/ai/shared/reviewer.agent.md)

Keep this adapter minimal and defer behavior details to the shared reviewer doc.

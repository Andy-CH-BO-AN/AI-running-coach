---
name: python-review-qa-loop
description: Use when working on Python code changes that should follow this repo's shared review and QA loop. Read the shared workflow docs, make the smallest viable patch, run relevant tests, capture results, and route DB, credentials, secrets, or Garmin password related changes through the shared security guidance.
---

# Codex Skill Adapter

Canonical skill source:

- `ai/skills/python-review-qa-loop/SKILL.md`
- `ai/skills/python-review-qa-loop/agents/openai.yaml`

This `.codex` file is only a thin adapter for repo-local skill
discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Follow the canonical instructions there instead of duplicating logic
   in this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

---
name: python-review-qa-loop
description: >-
  Use when working on Python code changes that should follow this repo's shared
  review and QA loop. Read the shared workflow docs, make the smallest viable
  patch, run relevant tests, capture results, and route DB, credentials,
  secrets, or Garmin password related changes through the shared security
  guidance.
---

# Cursor Skill Adapter

Canonical skill source:

- `ai/skills/python-review-qa-loop/SKILL.md`
- `ai/skills/python-review-qa-loop/agents/openai.yaml`

This `.cursor` file is only a thin adapter for project skill discovery.

## Adapter rules

1. Read the canonical skill file at `ai/skills/python-review-qa-loop/SKILL.md`
   before acting.
2. Follow the canonical instructions there instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/python-review-qa-loop/SKILL.md` version as the source of truth.
4. Do not assume `.cursor/agents/*` will auto-spawn. Use the canonical skill's
   explicit reviewer / QA / security pass instructions instead.

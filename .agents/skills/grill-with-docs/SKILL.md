---
name: grill-with-docs
description: Antigravity adapter for the grill-with-docs skill. Read the canonical skill in ai/skills before acting.
disable-model-invocation: true
---

# Antigravity Skill Adapter

Canonical skill source:

- `ai/skills/grill-with-docs/SKILL.md`

This `.agents` file is only a thin adapter for Antigravity repo-local skill discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

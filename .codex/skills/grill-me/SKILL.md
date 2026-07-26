---
name: grill-me
description: A relentless interview to sharpen a plan or design.
disable-model-invocation: true
---

# Codex Skill Adapter

Canonical skill source:

- `ai/skills/grill-me/SKILL.md`
- `ai/skills/grill-me/agents/openai.yaml`

This `.codex` file is only a thin adapter for repo-local skill
discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Follow the canonical instructions there instead of duplicating logic
   in this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

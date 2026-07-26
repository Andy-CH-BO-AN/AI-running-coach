---
name: improve-codebase-architecture
description: >-
  Scan a codebase for deepening opportunities, present them as a visual HTML
  report, then grill through whichever one you pick.
disable-model-invocation: true
---

# Cursor Skill Adapter

Canonical skill source:

- `ai/skills/improve-codebase-architecture/SKILL.md`
- `ai/skills/improve-codebase-architecture/agents/openai.yaml`

This `.cursor` file is only a thin adapter for project skill discovery.

## Adapter rules

1. Read the canonical skill file at `ai/skills/improve-codebase-architecture/SKILL.md`
   before acting.
2. Follow the canonical instructions there instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/improve-codebase-architecture/SKILL.md` version as the source of truth.

---
name: grill-with-docs
description: >-
  A relentless interview to sharpen a plan or design, which also creates docs
  (ADR's and glossary) as we go.
---

# Cursor Skill Adapter

Canonical skill source:

- `ai/skills/grill-with-docs/SKILL.md`
- `ai/skills/grill-with-docs/agents/openai.yaml`

This `.cursor` file is only a thin adapter for project skill discovery.

## Adapter rules

1. Read the canonical skill file at `ai/skills/grill-with-docs/SKILL.md`
   before acting.
2. Follow the canonical instructions there instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/grill-with-docs/SKILL.md` version as the source of truth.

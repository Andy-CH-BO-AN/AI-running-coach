---
name: grilling
description: >-
  Grill the user relentlessly about a plan, decision, or idea. Use when the user
  wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

# Cursor Skill Adapter

Canonical skill source:

- `ai/skills/grilling/SKILL.md`
- `ai/skills/grilling/agents/openai.yaml`

This `.cursor` file is only a thin adapter for project skill discovery.

## Adapter rules

1. Read the canonical skill file at `ai/skills/grilling/SKILL.md`
   before acting.
2. Follow the canonical instructions there instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/grilling/SKILL.md` version as the source of truth.

---
name: codebase-design
description: >-
  Shared vocabulary for designing deep modules. Use when the user wants to
  design or improve a module's interface, find deepening opportunities, decide
  where a seam goes, make code more testable or AI-navigable, or when another
  skill needs the deep-module vocabulary.
---

# Cursor Skill Adapter

Canonical skill source:

- `ai/skills/codebase-design/SKILL.md`
- `ai/skills/codebase-design/agents/openai.yaml`

This `.cursor` file is only a thin adapter for project skill discovery.

## Adapter rules

1. Read the canonical skill file at `ai/skills/codebase-design/SKILL.md`
   before acting.
2. Follow the canonical instructions there instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/codebase-design/SKILL.md` version as the source of truth.

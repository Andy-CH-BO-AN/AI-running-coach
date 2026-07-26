---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when the user wants to pin down domain terminology or a ubiquitous language, record an architectural decision, or when another skill needs to maintain the domain model.
---

# Codex Skill Adapter

Canonical skill source:

- `ai/skills/domain-modeling/SKILL.md`
- `ai/skills/domain-modeling/agents/openai.yaml`

This `.codex` file is only a thin adapter for repo-local skill
discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Follow the canonical instructions there instead of duplicating logic
   in this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

---
name: git-change-conventions
description: Antigravity adapter for the git-change-conventions skill. Read the canonical skill in ai/skills before acting.
---

# Antigravity Skill Adapter

Canonical skill source:

- `ai/skills/git-change-conventions/SKILL.md`

This `.agents` file is only a thin adapter for Antigravity repo-local skill discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

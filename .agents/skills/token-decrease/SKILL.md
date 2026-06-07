---
name: token-decrease
description: >-
  Default concise communication overlay for this repository. Read the canonical
  skill before acting, keep it active by default, and switch to normal wording
  when safety, irreversible actions, or clarity need more explicit phrasing.
---

# Antigravity Skill Adapter

Canonical skill source:

- `ai/skills/token-decrease/SKILL.md`

This `.agents` file is only a thin adapter for Antigravity repo-local skill discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Keep the canonical skill active by default for concise responses.
3. If clarity, safety, or irreversible actions need more explicit wording,
   temporarily switch to normal phrasing.
4. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

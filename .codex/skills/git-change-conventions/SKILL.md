---
name: git-change-conventions
description: Use when creating or naming branches, pull requests, or commits in this repository. Follow the repo's required type prefixes for branch and PR titles, and write detailed commit messages.
---

# Codex Skill Adapter

Canonical skill source:

- `ai/skills/git-change-conventions/SKILL.md`
- `ai/skills/git-change-conventions/agents/openai.yaml`

This `.codex` file is only a thin adapter for repo-local skill
discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Follow the canonical instructions there instead of duplicating logic
   in this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.

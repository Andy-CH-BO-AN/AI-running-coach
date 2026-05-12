---
name: readme-pm-review
description: Use only when the user explicitly asks for a product-manager style review of a repository README. Read only the README first, do not infer undocumented features, and provide readability feedback, rewrite suggestions, and product-priority recommendations.
---

# Codex Skill Adapter

Canonical skill source:

- `ai/skills/readme-pm-review/SKILL.md`
- `ai/skills/readme-pm-review/agents/openai.yaml`

This `.codex` file is only a thin adapter for repo-local skill
discovery.

## Adapter rules

1. Read the canonical skill file in `ai/skills/...` before acting.
2. Follow the canonical instructions there instead of duplicating logic
   in this adapter.
3. If this adapter and the canonical skill ever diverge, treat the
   `ai/skills/...` version as the source of truth.
